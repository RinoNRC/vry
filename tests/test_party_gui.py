import unittest
from unittest.mock import Mock, patch

from src.constants import DEFAULT_CONFIG
from src.gui import ALLY, PARTY_COLORS, ValorantApp, _party_badge
from src.stat_format import recent_stats_caption


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [control.value for control in controls(root) if isinstance(getattr(control, "value", None), str)]


def party_badges(root):
    return [control for control in controls(root) if isinstance(getattr(control, "tooltip", None), str) and control.tooltip.startswith("Пати ")]


class PartyGuiTests(unittest.TestCase):
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
            "team": "Blue", "agent": "Sage", "partyNumber": 1, "partySize": 2,
            "headshotPercentage": 25, "kd": 1.2,
            "recentStats": {"status": "ready", "matches": 12, "availableMatches": 12},
        }

    def test_badge_is_readable_and_explains_party_and_in_match_size(self):
        badge = _party_badge(self.player)
        self.assertIsNot(badge.visible, False)
        self.assertEqual(labels(badge), ["ПАТИ 1"])
        self.assertGreaterEqual(badge.content.size, 10)
        self.assertTrue(badge.content._get_attr("noWrap", data_type="bool"))
        self.assertIn("одинаковый номер", badge.tooltip)
        self.assertIn("одной пати", badge.tooltip)
        self.assertIn("Участников этой пати в матче: 2", badge.tooltip)
        self.assertIsNotNone(badge.border)

    def test_only_positive_integer_party_numbers_are_visible(self):
        for number in (None, False, True, 0, -1, "1", "invalid", 1.0, [], {}):
            with self.subTest(number=number):
                badge = _party_badge({"partyNumber": number, "partySize": 2})
                self.assertFalse(badge.visible)
                self.assertEqual(labels(badge), [])
        self.assertFalse(_party_badge({}).visible)
        for number in (1, 2, 10, 100):
            with self.subTest(number=number):
                self.assertEqual(labels(_party_badge({"partyNumber": number})), [f"ПАТИ {number}"])

    def test_missing_or_invalid_size_does_not_claim_a_party_size(self):
        for size in (None, False, True, 0, -1, "2", 2.0, [], {}):
            with self.subTest(size=size):
                badge = _party_badge({"partyNumber": 1, "partySize": size})
                self.assertNotIn("Участников", badge.tooltip)
        self.assertNotIn("Участников", _party_badge({"partyNumber": 1}).tooltip)

    def test_party_colors_are_deterministic_and_distinct_for_match_parties(self):
        colors = [_party_badge({"partyNumber": number}).content.color for number in range(1, 11)]
        self.assertEqual(len(set(colors)), 10)
        self.assertEqual(colors, list(PARTY_COLORS))
        for number, color in enumerate(colors, 1):
            self.assertEqual(_party_badge({"partyNumber": number, "name": "Other"}).content.color, color)

    def test_shared_badge_in_team_card_and_both_table_layouts(self):
        views = [
            self.app._team_player_card(self.player, False, ALLY),
            self.app._player_row(self.player),
            self.app._player_row(self.player, is_self=True, compact=True),
        ]
        for view in views:
            with self.subTest(view=view):
                badges = party_badges(view)
                self.assertEqual(len(badges), 1)
                self.assertEqual(labels(badges[0]), ["ПАТИ 1"])
                self.assertEqual(badges[0].content.color, PARTY_COLORS[0])
                self.assertIn("Участников этой пати в матче: 2", badges[0].tooltip)
                captions = [getattr(control, "tooltip", None) for control in controls(view)]
                self.assertIn(recent_stats_caption(self.player), captions)

    def test_invalid_number_has_no_badge_in_cards_or_rows(self):
        for number in (None, 0, True, "1"):
            player = self.player | {"partyNumber": number}
            for view in (self.app._team_player_card(player, False, ALLY), self.app._player_row(player)):
                with self.subTest(number=number):
                    self.assertEqual(party_badges(view), [])

    def test_menus_table_shows_same_party_for_members_and_no_badge_for_solo(self):
        second = self.player | {"puuid": "second", "name": "Second#EU"}
        solo = self.player | {"puuid": "solo", "name": "Solo#EU", "partyNumber": None}
        self.app.snapshot = {"heartbeat": {
            "state": "MENUS", "puuid": "self", "mode": "Competitive",
            "players": {"self": self.player, "second": second, "solo": solo},
        }}
        view = self.app._match_view()
        badges = party_badges(view)
        self.assertEqual(len(badges), 2)
        self.assertTrue(all(labels(badge) == ["ПАТИ 1"] for badge in badges))
        self.assertEqual(badges[0].content.color, badges[1].content.color)
        self.assertIn("Solo#EU", labels(view))


if __name__ == "__main__":
    unittest.main()
