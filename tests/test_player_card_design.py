import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ALLY, ENEMY, SELF_SURFACE, SUCCESS, TEXT, WARNING, ValorantApp
from src.stat_format import recent_stats_caption


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [item.value for item in controls(root) if isinstance(item, ft.Text)]


class PlayerCardDesignTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("src.gui.Stats").start()
        store = patch("src.gui.app_state").start()
        store.snapshot.return_value = {"revision": 0, "heartbeat": None}
        patch.object(ValorantApp, "_load_settings", return_value=dict(DEFAULT_CONFIG["table"])).start()
        patch.object(ValorantApp, "_load_feature_settings", return_value=dict(DEFAULT_CONFIG["flags"])).start()
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)
        self.player = {
            "puuid": "other", "name": "Player#EU", "agent": "Sage", "rank": 12,
            "rr": 52, "peakRank": 15, "previousRank": 9, "partyNumber": 2, "partySize": 2,
            "headshotPercentage": 25, "kd": 1.5, "earnedRR": 18, "winPercentage": "56%",
            "recentStats": {"status": "ready", "matches": 1, "availableMatches": 1},
            "skin": "Example Vandal", "weapons": {"vandal": {"weapon": "Vandal", "skinDisplayName": "Example Vandal"}},
        }

    def test_card_sections_separate_sources_and_show_party(self):
        self.app._show_player_card(self.player)
        values = labels(self.app.player_panel)
        for label in ("ПРОФИЛЬ ИГРОКА", "ТЕКУЩИЙ РАНГ", "ПОСЛЕДНИЙ РЕЙТИНГОВЫЙ МАТЧ", "ТЕКУЩИЙ АКТ", "ЛОКАЛЬНЫЕ ВСТРЕЧИ", "СКИНЫ И ОРУЖИЕ", "ПАТИ 2"):
            self.assertIn(label, values)
        self.assertIn(recent_stats_caption(self.player), values)
        self.assertIn("+18", values)
        self.assertIn("25%", values)
        self.assertIn("1.5", values)
        self.assertFalse(self.app.player_inventory_container.visible)
        self.assertIsNone(self.app.history_match_id)

    def test_card_statistics_use_soft_semantic_colors(self):
        self.app._show_player_card(self.player)
        for value, color in (("25%", WARNING), ("1.5", SUCCESS), ("56%", SUCCESS), ("52", TEXT)):
            texts = [item for item in controls(self.app.player_panel) if isinstance(item, ft.Text) and item.value == value]
            self.assertTrue(texts)
            self.assertTrue(all(item.color == color for item in texts))
        delta = next(item for item in controls(self.app.player_panel) if isinstance(item, ft.Text) and item.value == "+18")
        self.assertEqual(delta.color, SUCCESS)

    def test_live_metrics_have_consistent_color_mapping(self):
        for key, color in (("rr", None), ("headshot_percent", WARNING), ("kd", SUCCESS), ("winrate", SUCCESS)):
            self.assertEqual(self.app._heat_color(key, self.player), color)
        self.assertEqual(self.app._heat_color("earned_rr", self.player), SUCCESS)
        self.assertEqual(self.app._heat_color("earned_rr", {"earnedRR": -18}), ENEMY)
        for value in (None, True, False, "N/A", 0, float("nan"), float("inf")):
            self.assertIsNone(self.app._heat_color("earned_rr", {"earnedRR": value}))

    def test_missing_metrics_remain_unknown_and_inventory_can_expand(self):
        self.app._show_player_card({"puuid": "unknown", "name": "Unknown"})
        self.assertGreaterEqual(labels(self.app.player_panel).count("—"), 4)
        self.assertIn("Инвентарь недоступен для этого состояния игры.", labels(self.app.player_panel))
        self.assertFalse(self.app.player_inventory_container.visible)
        self.app._toggle_player_inventory(None)
        self.assertTrue(self.app.player_inventory_container.visible)

    def test_local_encounter_excludes_current_match(self):
        self.app.snapshot = {"heartbeat": {"matchId": "active", "puuid": "self"}}
        self.app.encounters = {"other": {"count": 3}}
        self.app.history = [{"match_id": "active", "players": {"other": self.player}}]
        self.app._show_player_card(self.player)
        values = labels(self.app.player_panel)
        self.assertIn("Предыдущих встреч: 2", values)
        self.assertIn("Только сохранённые на этом устройстве матчи", values)

    def test_own_profile_does_not_claim_repeat_encounters(self):
        self.app.snapshot = {"heartbeat": {"puuid": "other"}}
        self.app.encounters = {"other": {"count": 10}}
        self.app._show_player_card(self.player)
        self.assertIn("Это ваш профиль. Встречи с самим собой не учитываются.", labels(self.app.player_panel))

    def test_privacy_actions_stay_disabled(self):
        self.app._show_player_card(self.player | {"streamerMode": True, "name": "Hidden"})
        buttons = {item.text: item for item in controls(self.app.player_panel) if isinstance(item, ft.OutlinedButton)}
        self.assertTrue(buttons["Tracker.gg"].disabled)
        self.assertTrue(buttons["Скопировать ник"].disabled)
        self.app._open_tracker_profile(None)
        self.page.launch_url.assert_not_called()

    def test_panel_width_is_bounded_and_long_name_is_wrapped(self):
        self.page.width = 390
        name = "VeryLongPlayerName" * 10
        self.app._show_player_card(self.player | {"name": name})
        self.assertLessEqual(self.app.player_panel.width, self.page.width - 24)
        text = next(item for item in controls(self.app.player_panel) if isinstance(item, ft.Text) and item.value == name)
        self.assertEqual(text.max_lines, 2)
        ranks = [item for item in controls(self.app.player_panel) if isinstance(item, ft.Container) and item.col == 6]
        self.assertGreaterEqual(len(ranks), 4)

    def test_history_to_live_card_resets_drawer_context(self):
        self.app.history_match_id = "past"
        self.app.player_panel_open = True
        self.app.selected_player = self.player
        self.app.player_inventory_open = True
        self.app._show_player_card(self.player)
        self.assertIsNone(self.app.history_match_id)
        self.assertFalse(self.app.player_inventory_open)

    def test_current_player_uses_soft_blue_highlight_and_hover_restores_it(self):
        row = self.app._team_player_card(self.player, True, ALLY)
        self.assertEqual(row.bgcolor, SELF_SURFACE)
        row.update = Mock()
        self.app._player_hover(SimpleNamespace(data="true", control=row), True)
        self.app._player_hover(SimpleNamespace(data="false", control=row), True)
        self.assertEqual(row.bgcolor, SELF_SURFACE)
        self.assertEqual(row.border.top.color, ft.Colors.with_opacity(0.40, ALLY))


if __name__ == "__main__":
    unittest.main()
