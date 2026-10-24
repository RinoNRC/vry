import unittest

import flet as ft

from src.gui import ENEMY, SUCCESS, TEXT, WARNING, ValorantApp
from tests import test_player_card_design as card_tests

controls = card_tests.controls


class StatColorTests(unittest.TestCase):
    setUp = card_tests.PlayerCardDesignTests.setUp
    def test_scale_boundaries(self):
        for key, low, high in (("headshot_percent", 18, 28), ("winrate", 47, 53), ("kd", 0.9, 1.15), ("adr", 120, 150)):
            for value, expected in ((0, ENEMY), (low - 0.01, ENEMY), (low, WARNING), (high - 0.01, WARNING), (high, SUCCESS)):
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.app._stat_color(key, value), expected)
            for invalid in (None, True, False, "—", "N/A", "", " ", [], {}, float("nan"), float("inf"), -1):
                with self.subTest(key=key, invalid=invalid):
                    self.assertIsNone(self.app._stat_color(key, invalid))
        self.assertIsNone(self.app._stat_color("winrate", 101))
        self.assertIsNone(self.app._stat_color("headshot_percent", 101))

    def test_wr_formats_include_live_game_count(self):
        for value in ("56 (25)", "56% (25)", " 56% ", 56):
            self.assertEqual(self.app._stat_color("winrate", value), SUCCESS)
        for key in ("rr", "level", "leaderboard", "skin", "kills", "deaths", "assists"):
            self.assertIsNone(self.app._stat_color(key, 20))

    def test_table_has_colored_text_subtle_fill_and_no_border(self):
        for key, color in (("headshot_percent", WARNING), ("winrate", SUCCESS), ("kd", SUCCESS), ("earned_rr", SUCCESS)):
            cell = self.app._player_cell(key, self.player, 1)
            badge = cell.content
            self.assertEqual(badge.bgcolor, ft.Colors.with_opacity(0.09, color))
            self.assertIsNone(badge.border)
            self.assertEqual(badge.content.color, color)
        unknown = self.app._player_cell("kd", {"kd": None}, 1)
        self.assertIsInstance(unknown.content, ft.Text)
        self.assertEqual(unknown.content.color, TEXT)

    def test_history_uses_saved_stats_not_live_fields(self):
        row = self.app._history_player_row({"hs": 12, "headshotPercentage": 90, "kd": 1.5, "adr": 135})
        texts = {item.value: item for item in controls(row) if isinstance(item, ft.Text)}
        self.assertEqual(texts["12%"].color, ENEMY)
        self.assertEqual(texts["1.5"].color, SUCCESS)
        self.assertEqual(texts["135"].color, WARNING)
        self.assertIn("<18%", texts["12%"].tooltip)

    def test_legend_explains_sample_limits(self):
        legend = self.app._stats_color_legend()
        hint = legend.controls[-1].tooltip
        self.assertIn("не оценка навыка", hint)
        self.assertIn("одной прошлой игре", hint)
        self.assertTrue(legend.wrap)


if __name__ == "__main__":
    unittest.main()
