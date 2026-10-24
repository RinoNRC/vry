import unittest
from unittest.mock import Mock

from src.gui import ValorantApp


def texts(control):
    found = []
    if isinstance(getattr(control, "value", None), str):
        found.append(control.value)
    for child in control._get_children():
        found.extend(texts(child))
    return found


class RecentStatsGuiTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)
        self.player = {
            "puuid": "self", "name": "Example#EU", "rank": 9, "rr": 50,
            "headshotPercentage": 25, "kd": 1.2, "team": "Blue", "agent": "Sage",
            "recentStats": {"status": "ready", "matches": 12, "availableMatches": 12},
        }
        self.heartbeat = {
            "state": "INGAME", "matchId": "active", "puuid": "self", "ownTeam": "Blue",
            "mode": "Competitive", "map": "Bind", "players": {"self": self.player},
        }
        self.app.snapshot = {"heartbeat": self.heartbeat}
        self.app.stats_store = Mock()
        self.app.stats_store.get_player_history.return_value = []

    def test_match_hero_labels_recent_source(self):
        labels = texts(self.app._match_hero(self.heartbeat, compact=True))
        self.assertTrue(any("ПОСЛЕДНИЙ РЕЙТИНГОВЫЙ МАТЧ" in label for label in labels))

    def test_cells_display_aggregate(self):
        self.assertIn("25%", texts(self.app._player_cell("headshot_percent", self.player, 1)))
        self.assertIn("1.2", texts(self.app._player_cell("kd", self.player, 1)))

    def test_refreshing_same_player_keeps_inventory_open(self):
        self.app._show_player_card(self.player)
        self.app._toggle_player_inventory(None)
        self.app._show_player_card(self.player | {"recentStats": {"matches": 13}})
        self.assertTrue(self.app.player_inventory_open)
        self.assertTrue(self.app.player_inventory_container.visible)
        self.app._show_player_card(self.player | {"puuid": "other"})
        self.assertFalse(self.app.player_inventory_open)

    def test_card_and_account_label_actual_sample(self):
        self.app._show_player_card(self.player)
        card = texts(self.app.player_panel)
        self.assertTrue(any("учтено 12" in label for label in card))
        account = texts(self.app._account_view())
        self.assertTrue(any("учтено 12" in label for label in account))


if __name__ == "__main__":
    unittest.main()
