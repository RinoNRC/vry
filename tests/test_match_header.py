import unittest
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ALLY, ENEMY, ValorantApp
from src.match_context import pregame_own_team, starting_side


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [control.value for control in controls(root) if isinstance(control, ft.Text)]


class MatchContextTests(unittest.TestCase):
    def test_standard_starting_assignments_are_not_current_sides(self):
        for state in ("PREGAME", "INGAME"):
            for mode in ("Competitive", "Unrated", "Swiftplay", "Spike Rush", "Premier"):
                self.assertEqual(starting_side({"ownTeam": "Red", "mode": mode, "state": state}), "attack")
                self.assertEqual(starting_side({"ownTeam": "Blue", "mode": mode, "state": state}), "defense")

    def test_no_side_for_other_modes_or_missing_context(self):
        for mode in (None, "", "Deathmatch", "Team Deathmatch", "Escalation", "Custom Game", "Unknown"):
            self.assertIsNone(starting_side({"ownTeam": "Red", "mode": mode, "state": "INGAME"}))
        for state in (None, "MENUS", "DISCONNECTED"):
            self.assertIsNone(starting_side({"ownTeam": "Blue", "mode": "Competitive", "state": state}))
        for team in (None, "", "Neutral", [], True):
            self.assertIsNone(starting_side({"ownTeam": team, "mode": "Competitive", "state": "INGAME"}))

    def test_pregame_uses_ally_not_first_team(self):
        data = {"AllyTeam": {"TeamID": "Red", "Players": [{"Subject": "self"}]},
                "Teams": [{"TeamID": "Blue", "Players": [{"Subject": "enemy"}]},
                          {"TeamID": "Red", "Players": [{"Subject": "self"}]}]}
        self.assertEqual(pregame_own_team(data, "self"), "Red")

    def test_pregame_fallback_requires_membership(self):
        data = {"Teams": [None, {"TeamID": "Blue", "Players": [{"Subject": "enemy"}]},
                          {"TeamID": "Red", "Players": [None, {"Subject": "self"}]}]}
        self.assertEqual(pregame_own_team(data, "self"), "Red")
        self.assertIsNone(pregame_own_team(data, "missing"))
        for data in ({}, {"Teams": None}, {"Teams": {}}, {"AllyTeam": None, "Teams": [None]}):
            self.assertIsNone(pregame_own_team(data, "self"))


class MatchHeaderTests(unittest.TestCase):
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
        self.heartbeat = {"state": "INGAME", "mode": "Competitive", "map": "Ascent", "ownTeam": "Red",
                          "server": "eu-gp-frankfurt-1", "players": {str(i): {} for i in range(10)}}

    def test_single_starting_side_badge_replaces_team_duplicates(self):
        hero = self.app._match_hero(self.heartbeat, compact=True)
        texts = labels(hero)
        self.assertEqual(texts.count("Атака"), 1)
        self.assertEqual(texts.count("Ascent"), 1)
        self.assertIn("СТАРТОВАЯ СТОРОНА", texts)
        self.assertIn("В МАТЧЕ", texts)
        self.assertIn("Франкфурт", texts)
        self.assertIn("10 игроков", texts)
        self.assertNotIn("Красная команда", texts)
        self.assertNotIn("Синяя команда", texts)
        badge = next(control for control in controls(hero) if isinstance(getattr(control, "tooltip", None), str) and "Стартовая сторона" in control.tooltip)
        self.assertIn("не отслеживается", badge.tooltip)
        attack = next(control for control in controls(hero) if isinstance(control, ft.Text) and control.value == "Атака")
        self.assertEqual(attack.color, ENEMY)

    def test_blue_defense_and_pregame_status(self):
        hero = self.app._match_hero(self.heartbeat | {"ownTeam": "Blue", "state": "PREGAME"})
        texts = labels(hero)
        self.assertIn("ВЫБОР АГЕНТА", texts)
        self.assertEqual(texts.count("Защита"), 1)
        defense = next(control for control in controls(hero) if isinstance(control, ft.Text) and control.value == "Защита")
        self.assertEqual(defense.color, ALLY)

    def test_missing_or_non_side_mode_never_claims_attack(self):
        for heartbeat in ({}, self.heartbeat | {"mode": "Deathmatch"}, self.heartbeat | {"ownTeam": None}):
            texts = labels(self.app._match_hero(heartbeat))
            self.assertIn("Нет данных", texts)
            self.assertNotIn("Атака", texts)
            self.assertNotIn("Защита", texts)

    def test_source_and_party_limitation_remain_available(self):
        hero = self.app._match_hero(self.heartbeat)
        self.assertIn("HS% / K/D · ПОСЛЕДНИЙ РЕЙТИНГОВЫЙ МАТЧ", labels(hero))
        hints = [control.tooltip for control in controls(hero) if isinstance(getattr(control, "tooltip", None), str)]
        self.assertTrue(any("WR — за текущий акт" in hint for hint in hints))
        self.assertTrue(any("отсутствие метки не означает соло" in hint for hint in hints))

    def test_map_image_has_fallback_and_long_map_is_truncated(self):
        name = "Long map " * 30
        hero = self.app._match_hero(self.heartbeat | {"map": name, "mapSplash": "mock://splash"})
        image = next(control for control in controls(hero) if isinstance(control, ft.Image))
        self.assertIsNotNone(image.error_content)
        title = next(control for control in controls(hero) if isinstance(control, ft.Text) and control.value == name)
        self.assertEqual(title.max_lines, 1)
        self.assertEqual(title.overflow, ft.TextOverflow.ELLIPSIS)
        self.assertEqual(hero.height, 166)


if __name__ == "__main__":
    unittest.main()
