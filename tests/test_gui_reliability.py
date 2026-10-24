import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.constants import DEFAULT_CONFIG
from src.gui import ENEMY, ValorantApp


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def labels(root):
    return [control.value for control in controls(root) if isinstance(getattr(control, "value", None), str)]


class GuiReliabilityTests(unittest.TestCase):
    def setUp(self):
        directory = Path("C:/Temp/opencode")
        self.directory = tempfile.TemporaryDirectory(dir=directory if directory.exists() else None)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.addCleanup(patch.stopall)
        patch("src.gui._config_path", return_value=self.path).start()
        patch("src.gui.Stats").start()
        self.store = patch("src.gui.app_state").start()
        self.store.snapshot.return_value = {"revision": 0, "heartbeat": None}
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)

    def write_config(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def run_refresh(self, snapshot=None, view=0, iterations=1):
        self.app.selected_view = view
        self.app.render = Mock()
        self.app.status_text.update = Mock()
        self.app.status_dot.update = Mock()
        self.app.status_panel.update = Mock()
        self.app._handle_notifications = Mock()
        self.app.last_revision = 0
        if snapshot is None:
            self.store.get_revision.return_value = 0
        else:
            snapshot = {"revision": 1, **snapshot}
            self.store.get_revision.return_value = 1
            self.store.snapshot.return_value = snapshot
        clock = [0]
        sleeps = [0]

        async def sleep(_):
            clock[0] += 0.75
            sleeps[0] += 1
            if sleeps[0] >= iterations:
                raise asyncio.CancelledError

        with patch("src.gui.asyncio.sleep", side_effect=sleep), patch("src.gui.time", wraps=time) as gui_time:
            gui_time.monotonic.side_effect = lambda: clock[0]
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.app.refresh_loop())

    def test_loading_invalid_roots_and_sections_uses_defaults(self):
        for value in (None, [], ["table"], 1, "text", {"table": [], "flags": None}):
            with self.subTest(value=value):
                self.write_config(value)
                self.assertEqual(self.app._load_settings(), DEFAULT_CONFIG["table"])
                self.assertEqual(self.app._load_feature_settings(), DEFAULT_CONFIG["flags"])

    def test_loading_wrong_value_types_uses_defaults(self):
        self.write_config({"table": {"skin": "false", "rank_icon_style": []}, "flags": {"notifications": 0}})
        self.assertEqual(self.app._load_settings(), DEFAULT_CONFIG["table"])
        self.assertEqual(self.app._load_feature_settings(), DEFAULT_CONFIG["flags"])

    def test_valid_settings_load(self):
        self.write_config({"table": {"skin": False, "rank_icon_style": "minimal"}, "flags": {"notifications": False}})
        self.assertFalse(self.app._load_settings()["skin"])
        self.assertEqual(self.app._load_settings()["rank_icon_style"], "minimal")
        self.assertFalse(self.app._load_feature_settings()["notifications"])

    def test_corrupt_json_and_invalid_root_are_not_overwritten(self):
        for original in (b"{broken", b"[]", b"null", b"\xff\xfe"):
            with self.subTest(original=original):
                self.path.write_bytes(original)
                self.assertFalse(self.app._save_setting("skin", False))
                self.assertFalse(self.app._save_feature_setting("notifications", False))
                self.app.render = Mock()
                self.app._reset_settings(None)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertTrue(self.app.settings["skin"])
                self.assertTrue(self.app.feature_settings["notifications"])
        self.assertTrue(self.page.open.called)

    def test_save_repairs_wrong_section_types(self):
        self.write_config({"table": [], "flags": "invalid", "weapon": "Phantom"})
        self.assertTrue(self.app._save_setting("skin", False))
        self.assertTrue(self.app._save_feature_setting("notifications", False))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"table": {"skin": False}, "flags": {"notifications": False}, "weapon": "Phantom"})

    def test_save_preserves_unrelated_changes_and_unknown_keys(self):
        self.write_config({"table": {"rr": False, "custom": "keep"}, "flags": {"notifications": False}, "other": {"keep": 1}})
        self.app._save_setting("skin", False)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(saved["table"]["rr"])
        self.assertFalse(saved["table"]["skin"])
        self.assertEqual(saved["table"]["custom"], "keep")
        self.assertEqual(saved["other"], {"keep": 1})
        self.assertFalse(saved["flags"]["notifications"])

    def test_save_missing_file_uses_defaults(self):
        self.assertTrue(self.app._save_setting("skin", False))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["weapon"], DEFAULT_CONFIG["weapon"])
        self.assertFalse(saved["table"]["skin"])
        self.assertEqual(saved["flags"], DEFAULT_CONFIG["flags"])

    def test_atomic_failure_preserves_file_and_memory_and_cleans_temp(self):
        self.write_config({"table": {"skin": True}})
        original = self.path.read_bytes()
        with patch("src.config.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(self.app._save_setting("skin", False))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.app.settings["skin"])
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.page.open.assert_called_once()

    def test_reset_handles_write_error_without_crashing(self):
        self.app.render = Mock()
        with patch("src.gui.save_config", side_effect=OSError("read only")):
            self.app._reset_settings(None)
        self.app.render.assert_called_once()
        self.page.open.assert_called_once()

    def test_failed_card_toggle_keeps_previous_state(self):
        self.path.write_text("{broken", encoding="utf-8")
        card = self.app._toggle_setting_card("table", "skin", "Skin", "Description", "icon")
        card.on_click(None)
        self.assertTrue(self.app.settings["skin"])
        self.assertIn("ВКЛ", labels(card))

    def test_diagnostics_refresh_on_revision(self):
        self.run_refresh({"heartbeat": None, "error": "offline"}, view=2)
        self.app.render.assert_called_once()

    def test_diagnostics_refresh_while_idle(self):
        self.run_refresh(view=2, iterations=9)
        self.app.render.assert_called_once()

    def test_settings_do_not_refresh_while_idle(self):
        self.run_refresh(view=4, iterations=9)
        self.app.render.assert_not_called()

    def test_long_match_is_idle_not_connection_error(self):
        self.app.snapshot = {"heartbeat": {"state": "INGAME"}, "heartbeat_at": time.time() - 3600}
        view = self.app._diagnostics_view()
        self.assertIn("Ожидание событий", labels(view))
        self.assertNotIn("Нет обновлений", labels(view))
        self.assertFalse(any(getattr(control, "color", None) == ENEMY for control in controls(view)))

    def test_missing_heartbeat_and_timestamps_are_safe(self):
        self.app.snapshot = {"heartbeat": None, "heartbeat_at": None, "updated_at": None, "started_at": None}
        view = self.app._diagnostics_view()
        self.assertIn("Ожидание данных", labels(view))
        self.assertIn("Ещё не получен", labels(view))

    def test_diagnostics_error_is_red(self):
        self.app.snapshot = {"heartbeat": None, "error": "offline"}
        view = self.app._diagnostics_view()
        self.assertTrue(any(getattr(control, "value", None) == "Ошибка monitor" and control.color == ENEMY for control in controls(view)))

    def test_new_match_closes_live_card_even_for_same_player(self):
        self.app.snapshot = {"heartbeat": {"matchId": "old", "state": "INGAME"}}
        self.app.player_panel_open = True
        self.app.selected_player = {"puuid": "player"}
        self.run_refresh({"heartbeat": {"matchId": "new", "state": "INGAME", "players": {"player": self.app.selected_player}}})
        self.assertFalse(self.app.player_panel_open)
        self.app.render.assert_called_once()

    def test_updated_live_card_refreshes_in_same_match(self):
        heartbeat = {"matchId": "same", "state": "INGAME"}
        self.app.snapshot = {"heartbeat": heartbeat}
        self.app.player_panel_open = True
        self.app.selected_player = {"puuid": "player"}
        updated = {"puuid": "player", "recentStats": {"status": "ready"}}
        self.app._show_player_card = Mock()
        self.run_refresh({"heartbeat": heartbeat | {"players": {"player": updated}}})
        self.app._show_player_card.assert_called_once_with(updated)

    def test_missing_live_player_closes_card(self):
        self.app.player_panel_open = True
        self.app.selected_player = {"puuid": "player"}
        self.run_refresh({"heartbeat": None})
        self.assertFalse(self.app.player_panel_open)

    def test_live_revision_does_not_replace_history_card(self):
        self.app.player_panel_open = True
        self.app.history_match_id = "history"
        self.app.selected_player = {"puuid": "player"}
        self.app._show_player_card = Mock()
        self.run_refresh({"heartbeat": {"players": {"player": {"puuid": "player", "recentStats": {"status": "ready"}}}}}, view=1)
        self.app._show_player_card.assert_not_called()
        self.assertTrue(self.app.player_panel_open)
        self.assertEqual(self.app.history_match_id, "history")

    def test_revision_outside_match_does_not_open_live_card(self):
        self.app.player_panel_open = True
        self.app.selected_player = {"puuid": "player"}
        self.app._show_player_card = Mock()
        self.run_refresh({"heartbeat": {"players": {"player": {"puuid": "player", "recentStats": {"status": "ready"}}}}}, view=5)
        self.app._show_player_card.assert_not_called()


if __name__ == "__main__":
    unittest.main()
