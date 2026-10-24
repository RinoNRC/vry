import unittest
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ValorantApp, _party_badge


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [control.value for control in controls(root) if isinstance(getattr(control, "value", None), str)]


def tooltips(root):
    return [control.tooltip for control in controls(root) if isinstance(getattr(control, "tooltip", None), str)]


def party_badges(root):
    return [control for control in controls(root) if isinstance(getattr(control, "tooltip", None), str) and control.tooltip.startswith("Пати ")]


class HistoryPartyGuiTests(unittest.TestCase):
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
            "puuid": "self", "name": "Example#EU", "rank": 9, "rr": 50,
            "team": "Blue", "agent": "Sage", "kills": 20, "deaths": 10,
            "assists": 5, "kd": 2, "hs": 25, "adr": 150,
            "partyNumber": 1, "partySize": 2, "partyResolved": True,
            "partyId": "confirmed-party", "partySource": "match-results",
        }
        self.match = {
            "match_id": "completed", "epoch": 0, "map": "Bind", "mode": "Competitive",
            "account_puuid": "self", "players": {"self": self.player},
        }

    def test_history_badge_uses_shared_style_and_match_results_source(self):
        row = self.app._history_player_row(self.player, is_self=True)
        badges = party_badges(row)
        self.assertEqual(len(badges), 1)
        self.assertEqual(labels(badges[0]), ["ПАТИ 1"])
        self.assertEqual(badges[0].content.color, _party_badge(self.player).content.color)
        self.assertIn("по результатам этого матча", badges[0].tooltip)
        self.assertIn("Участников этой пати в матче: 2", badges[0].tooltip)
        self.assertIn("ВЫ", labels(row))
        self.assertIn("2", labels(row))
        self.assertIn("25%", labels(row))
        self.assertIn("20 / 10 / 5", labels(row))
        name_column = row.content.controls[1]
        self.assertTrue(name_column.expand)
        name_row = name_column.controls[0]
        self.assertIs(name_row.controls[1], badges[0])
        self.assertTrue(name_row.controls[0].expand)
        self.assertEqual(name_row.controls[0].overflow, ft.TextOverflow.ELLIPSIS)

    def test_same_history_party_is_consistent_and_distinct_from_other_group(self):
        second = self.player | {"puuid": "second", "name": "Second#EU"}
        other = self.player | {"puuid": "other", "partyNumber": 2, "partyId": "other-party"}
        rows = [self.app._history_player_row(player) for player in (self.player, second, other)]
        badges = [party_badges(row)[0] for row in rows]
        self.assertEqual(labels(badges[0]), labels(badges[1]))
        self.assertEqual(badges[0].content.color, badges[1].content.color)
        self.assertNotEqual(badges[0].content.color, badges[2].content.color)

    def test_history_pending_and_unavailable_are_not_reported_as_solo(self):
        cases = [
            ({"partyNumber": 0, "partyId": None, "partyResolved": False}, "ещё не проверены"),
            ({"partyNumber": 0, "partyId": None, "partyResolved": True}, "не предоставлены"),
            ({"partyNumber": 0, "partyId": "single-member", "partyResolved": True}, "Нет подтверждённой группы"),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                row = self.app._history_player_row(self.player | fields)
                self.assertEqual(party_badges(row), [])
                hints = tooltips(row)
                self.assertTrue(any(expected in hint for hint in hints))
                self.assertTrue(any("Отсутствие метки не означает соло" in hint for hint in hints))
                self.assertNotIn("СОЛО", labels(row))

    def test_legacy_history_row_is_unchecked_not_solo(self):
        player = {key: value for key, value in self.player.items() if not key.startswith("party")}
        row = self.app._history_player_row(player)
        self.assertEqual(party_badges(row), [])
        self.assertTrue(any("ещё не проверены" in hint for hint in tooltips(row)))

    def test_detail_explanation_and_all_player_party_states_are_visible(self):
        players = {
            "self": self.player,
            "second": self.player | {"puuid": "second", "name": "Second#EU"},
            "pending": self.player | {"puuid": "pending", "partyNumber": 0, "partyResolved": False, "partyId": None},
            "unavailable": self.player | {"puuid": "unavailable", "partyNumber": 0, "partyResolved": True, "partyId": None},
        }
        self.app._show_history_match(self.match | {"players": players})
        panel = self.app.player_panel
        self.assertIn("Пати определены по результатам этого матча. Без метки — нет подтверждённой группы.", labels(panel))
        self.assertEqual(len(party_badges(panel)), 2)
        self.assertTrue(any("ещё не проверены" in hint for hint in tooltips(panel)))
        self.assertTrue(any("не предоставлены" in hint for hint in tooltips(panel)))
        self.assertTrue(self.app.player_scrim.visible)
        self.assertEqual(self.app.history_match_id, "completed")

    def test_history_deathmatch_retains_party_badge_and_hides_kd_hs(self):
        row = self.app._history_player_row(self.player, is_deathmatch=True)
        self.assertEqual(len(party_badges(row)), 1)
        for column in row.content.controls:
            if isinstance(column, ft.Column) and any(label in ("K/D", "HS") for label in labels(column)):
                self.assertFalse(column.visible)

    def test_live_hero_explains_unknown_party_and_preserves_recent_stat_caption(self):
        heartbeat = {"state": "INGAME", "mode": "Competitive", "map": "Bind", "players": {"self": self.player}}
        for compact in (False, True):
            with self.subTest(compact=compact):
                hero = self.app._match_hero(heartbeat, compact=compact)
                self.assertIn("Показаны только подтверждённые пати; отсутствие метки не означает соло.", tooltips(hero))
                caption = next(control for control in controls(hero) if isinstance(control, ft.Text) and "ПОСЛЕДНИЙ РЕЙТИНГОВЫЙ МАТЧ" in str(control.value))
                self.assertIn("не текущей игры", caption.tooltip)
                self.assertTrue(caption.expand)
                self.assertEqual(caption.max_lines, 1)
                self.assertEqual(caption.overflow, ft.TextOverflow.ELLIPSIS)
                self.assertEqual(hero.height, 150 if compact else 166)

    def test_live_badge_does_not_claim_match_results_without_that_source(self):
        live = self.player | {"partySource": "party-roster"}
        badge = _party_badge(live)
        self.assertNotIn("результатам", badge.tooltip)
        self.assertIn("одной пати", badge.tooltip)


if __name__ == "__main__":
    unittest.main()
