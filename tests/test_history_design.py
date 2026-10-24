import unittest
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ALLY, ENEMY, MUTED, SELF_SURFACE, TEXT, ValorantApp
from src.stat_format import STATS_PENDING


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [control.value for control in controls(root) if isinstance(getattr(control, "value", None), str)]


def badges(root):
    return [control for control in controls(root) if isinstance(getattr(control, "tooltip", None), str) and control.tooltip.startswith("Пати ")]


class HistoryDesignTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.stats = patch("src.gui.Stats").start().return_value
        store = patch("src.gui.app_state").start()
        store.snapshot.return_value = {"revision": 0, "heartbeat": None}
        patch.object(ValorantApp, "_load_settings", return_value=dict(DEFAULT_CONFIG["table"])).start()
        patch.object(ValorantApp, "_load_feature_settings", return_value=dict(DEFAULT_CONFIG["flags"])).start()
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)
        self.player = {
            "puuid": "self", "name": "Example#EU", "team": "Blue", "agent": "Sage",
            "rank": 9, "rr": 50, "kills": 20, "deaths": 10, "assists": 5,
            "kd": 2, "hs": 25, "adr": 150, "partyNumber": 1, "partySize": 2,
            "partyResolved": True, "partyId": "own-party", "partySource": "match-results",
        }
        self.opponent = self.player | {
            "puuid": "enemy", "name": "Enemy#EU", "team": "Red", "kills": 99,
            "deaths": 40, "assists": 30, "adr": 999, "partyNumber": 0,
            "partyResolved": False, "partyId": None, "partySource": None,
        }
        self.match = {
            "match_id": "saved-match", "map": "Bind", "mode": "Competitive", "epoch": 100,
            "account_puuid": "self", "players": {"self": self.player, "enemy": self.opponent},
        }

    def test_card_uses_personal_kda_not_roster_totals(self):
        card = self.app._history_match_card(self.match)
        text = labels(card)
        self.assertIn("ВАШ K / D / A", text)
        self.assertIn("20 / 10 / 5", text)
        self.assertNotIn("119", " ".join(text))
        self.assertNotIn("99 / 40 / 30", text)
        self.assertIn("Bind", text)
        self.assertIn("Competitive", text)
        self.assertTrue(any("1970" in value for value in text))
        card.on_click(None)
        self.page.run_task.assert_called_once_with(self.app._deferred_history_open, self.match)
        self.stats.assert_not_called()

    def test_missing_account_never_falls_back_to_live_account_or_other_player(self):
        self.app.snapshot = {"heartbeat": {"puuid": "enemy"}, "account": {"profile": {"puuid": "enemy"}}}
        for account in (None, "missing"):
            with self.subTest(account=account):
                match = self.match | {"account_puuid": account}
                self.assertIn("— / — / —", labels(self.app._history_match_card(match)))
                self.app._show_history_match(match)
                text = labels(self.app.player_panel)
                self.assertIn("Ожидание итогов матча", text)
                self.assertIn(STATS_PENDING, text)
                self_labels = [control for control in controls(self.app.player_panel) if isinstance(control, ft.Container) and isinstance(control.content, ft.Text) and control.content.value == "ВЫ"]
                self.assertTrue(all(control.visible is False for control in self_labels))

    def test_pending_invalid_and_zero_values_are_distinct(self):
        for value in (None, "N/A", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                personal = self.player | {field: value for field in ("kills", "deaths", "assists")}
                match = self.match | {"players": {"self": personal}}
                card = self.app._history_match_card(match)
                self.assertIn("— / — / —", labels(card))
                self.assertIn("Ожидание итогов матча", labels(card))
                self.assertTrue(any(getattr(control, "tooltip", None) == STATS_PENDING for control in controls(card)))
        personal = self.player | {"kills": 0, "deaths": 0, "assists": 0}
        card = self.app._history_match_card(self.match | {"players": {"self": personal}})
        self.assertIn("0 / 0 / 0", labels(card))
        self.assertIn("Статистика этого матча", labels(card))

    def test_partial_personal_stats_explain_missing_values(self):
        match = self.match | {"players": {"self": self.player | {"deaths": None}}}
        self.assertIn("20 / — / 5", labels(self.app._history_match_card(match)))
        self.assertIn("Данные матча неполные", labels(self.app._history_match_card(match)))
        self.app._show_history_match(match)
        self.assertIn(STATS_PENDING, labels(self.app.player_panel))
        self.assertIn("«—» означает, что данные не получены; это не нулевое значение.", labels(self.app.player_panel))

    def test_unknown_result_is_neutral_and_never_inferred_from_kda_or_rr(self):
        for kills, rr in ((0, -20), (99, 50)):
            with self.subTest(kills=kills, rr=rr):
                match = self.match | {"players": {"self": self.player | {"kills": kills, "earnedRR": rr}}}
                card = self.app._history_match_card(match)
                result = next(control for control in controls(card) if getattr(control, "value", None) == "Результат не сохранён")
                self.assertEqual(result.color, MUTED)
                self.assertFalse(any(word in " ".join(labels(card)).lower() for word in ("победа", "поражение", "loss", "victory")))
                self.app._show_history_match(match)
                self.assertIn("Результат не сохранён", labels(self.app.player_panel))

    def test_map_thumbnail_missing_and_image_error_have_fallback(self):
        fallback = self.app._history_map_image(self.match, width=88)
        self.assertIsInstance(fallback, ft.Container)
        self.assertIsInstance(fallback.content, ft.Icon)
        image = self.app._history_map_image(self.match | {"mapSplash": "mock://map-splash"}, width=88)
        self.assertIsInstance(image, ft.Image)
        self.assertEqual(image.src, "mock://map-splash")
        self.assertEqual(image.fit, ft.ImageFit.COVER)
        self.assertIsInstance(image.error_content, ft.Container)
        self.assertIsInstance(image.error_content.content, ft.Icon)

    def test_drawer_personal_summary_has_exact_match_source(self):
        self.app._show_history_match(self.match)
        panel = self.app.player_panel
        text = labels(panel)
        self.assertIn("ВАШ K / D / A", text)
        self.assertIn("ВАШ ADR", text)
        self.assertIn("ВАШ HS", text)
        self.assertIn("150", text)
        self.assertIn("25%", text)
        self.assertIn("Источник: сохранённые результаты именно этого матча.", text)
        self.assertIn("Match ID: saved-match", text)
        self.assertEqual(self.app.history_match_id, "saved-match")
        self.assertTrue(self.app.player_scrim.visible)
        self.page.launch_url.assert_not_called()

    def test_two_rosters_responsive_and_party_states_preserved(self):
        self.app._show_history_match(self.match)
        roster = self.app.player_panel.content.controls[-1]
        self.assertIsInstance(roster, ft.ResponsiveRow)
        self.assertEqual(len(roster.controls), 2)
        for section in roster.controls:
            self.assertEqual(section.col, {"xs": 12, "md": 6})
        self.assertIn("ВАША КОМАНДА", labels(roster.controls[0]))
        self.assertIn("ПРОТИВНИКИ", labels(roster.controls[1]))
        self.assertEqual(len(badges(roster)), 1)
        self.assertIn("по результатам этого матча", badges(roster)[0].tooltip)
        hints = [getattr(control, "tooltip", None) for control in controls(roster)]
        self.assertTrue(any(isinstance(hint, str) and "ещё не проверены" in hint for hint in hints))
        self.assertIn("Отсутствие метки не означает соло. Статус проверки доступен у имени игрока.", labels(self.app.player_panel))

    def test_self_team_color_and_unknown_team_players_are_not_lost(self):
        match = self.match | {"players": {
            "self": self.player | {"team": "Red"},
            "enemy": self.opponent | {"team": "Blue"},
            "unknown": self.opponent | {"puuid": "unknown", "team": None},
        }}
        sections = self.app._history_match_sections(match)
        self.assertEqual(sections[0][:2], ("ВАША КОМАНДА", ALLY))
        self.assertEqual(sections[1][:2], ("ПРОТИВНИКИ", ENEMY))
        self.assertEqual(sum(len(players) for _, _, players in sections), 3)
        self.assertEqual(sections[2][0], "КОМАНДА НЕ СОХРАНЕНА")

    def test_narrow_drawer_never_exceeds_viewport_and_rows_wrap(self):
        for width in (240, 320, 480):
            with self.subTest(width=width):
                self.page.width = width
                self.app._show_history_match(self.match)
                self.assertEqual(self.app.player_panel.width, width - 16)
                roster = self.app.player_panel.content.controls[-1]
                self_row = roster.controls[0].content.controls[1]
                self.assertEqual(self_row.bgcolor, SELF_SURFACE)
                self.assertIsInstance(self_row.content, ft.ResponsiveRow)
                name = self_row.content.controls[1].controls[0].controls[0]
                self.assertTrue(name.expand)
                self.assertEqual(name.overflow, ft.TextOverflow.ELLIPSIS)
                self.assertEqual(name.max_lines, 1)
                kda = next(column for column in self_row.content.controls if isinstance(column, ft.Column) and "K / D / A" in labels(column))
                self.assertEqual(kda.col["xs"], 6)

    def test_rr_is_neutral_and_missing_rr_is_not_zero(self):
        row = self.app._history_player_row(self.player)
        rr = next(control for control in controls(row) if getattr(control, "value", None) == "50 RR")
        self.assertEqual(rr.color, TEXT)
        row = self.app._history_player_row(self.player | {"rr": None})
        self.assertIn("— RR", labels(row))
        self.assertNotIn("0 RR", labels(row))

    def test_modes_filters_wrap_and_clear_remains_confirmed(self):
        self.app.history = [self.match, self.match | {"map": "Ascent", "mode": "Deathmatch"}, self.match | {"mode": None}]
        self.app.history_mode = "Deathmatch"
        self.app.render = Mock()
        view = self.app._history_view()
        cards = [control for control in view.controls[1].controls if isinstance(control, ft.Container) and control.on_click]
        self.assertEqual(len(cards), 1)
        self.assertIn("Ascent", labels(cards[0]))
        self.assertNotIn("Bind", labels(cards[0]))
        filters = view.controls[0].controls[1]
        self.assertTrue(filters.wrap)
        self.assertGreater(filters.run_spacing, 0)
        buttons = [control for control in filters.controls if isinstance(control, ft.OutlinedButton)]
        self.assertEqual({button.text for button in buttons}, {"Все", "Competitive", "Deathmatch", "Неизвестно"})
        next(button for button in buttons if button.text == "Все").on_click(None)
        self.assertEqual(self.app.history_mode, "Все")
        self.app.render.assert_called_once()
        clear = filters.controls[-1]
        self.assertIsInstance(clear, ft.TextButton)
        self.assertEqual(clear.style.color, MUTED)
        clear.on_click(None)
        self.page.open.assert_called_once()
        self.stats.clear_data.assert_not_called()

    def test_summary_chart_is_optional_and_collapsed_after_matches(self):
        self.app.history = [self.match]
        view = self.app._history_view()
        archive = view.controls[1]
        summary = archive.controls[-1]
        self.assertIsInstance(summary, ft.ExpansionTile)
        self.assertFalse(summary.initially_expanded)
        self.assertIn("АКТИВНОСТЬ ЗА 10 ДНЕЙ", labels(summary))
        self.assertIn("ПОПУЛЯРНЫЕ КАРТЫ", labels(summary))
        self.assertIn("ВАШ K / D / A", labels(archive.controls[-2]))

    def test_deathmatch_mode_aliases_keep_badges_and_hide_kd_hs(self):
        for mode in ("Deathmatch", "Death Match", "Team Deathmatch", "Team Death Match", "TDM"):
            with self.subTest(mode=mode):
                self.app._show_history_match(self.match | {"mode": mode})
                roster = self.app.player_panel.content.controls[-1]
                self.assertEqual(len(badges(roster)), 1)
                columns = [control for control in controls(roster) if isinstance(control, ft.Column) and labels(control) in (["K/D", "2"], ["HS", "25%"])]
                self.assertTrue(columns)
                self.assertTrue(all(column.visible is False for column in columns))
                self.assertIn("20 / 10 / 5", labels(roster))

    def test_missing_derived_stats_remain_partial_when_kda_is_known(self):
        for field in ("hs", "adr"):
            with self.subTest(field=field):
                match = self.match | {"players": {"self": self.player | {field: None}}}
                self.app._show_history_match(match)
                self.assertIn("Данные матча неполные", labels(self.app.player_panel))
                self.assertIn(STATS_PENDING, labels(self.app.player_panel))
                self.assertIn("20 / 10 / 5", labels(self.app.player_panel))

    def test_clear_history_only_mutates_mock_store_after_confirmation(self):
        self.app.history = [self.match]
        self.app.encounters = {"enemy": {"count": 2}}
        self.app.render = Mock()
        self.app._confirm_clear_history(None)
        dialog = self.page.open.call_args.args[0]
        self.stats.clear_data.assert_not_called()
        dialog.actions[0].on_click(None)
        self.stats.clear_data.assert_not_called()
        self.assertEqual(self.app.history, [self.match])
        dialog.actions[1].on_click(None)
        self.stats.clear_data.assert_called_once_with()
        self.assertEqual(self.app.history, [])
        self.assertEqual(self.app.encounters, {})
        self.app.render.assert_called_once_with()

    def test_empty_archive_keeps_filters_and_hides_clear(self):
        self.app.history_mode = "removed-mode"
        view = self.app._history_view()
        self.assertEqual(self.app.history_mode, "Все")
        self.assertIn("История пока пуста", labels(view))
        filters = view.controls[0].controls[1]
        self.assertTrue(filters.wrap)
        self.assertFalse(filters.controls[-1].visible)

    def test_legacy_empty_match_is_safe(self):
        match = {"match_id": "legacy"}
        card = self.app._history_match_card(match)
        self.assertIn("— / — / —", labels(card))
        self.assertIn("Дата не сохранена", labels(card))
        self.app._show_history_match(match)
        self.assertIn("Ожидание итогов матча", labels(self.app.player_panel))
        self.assertIn("Match ID: legacy", labels(self.app.player_panel))


if __name__ == "__main__":
    unittest.main()
