import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from src.config import Config, application_root, config_path, save_config
from src.constants import DEFAULT_CONFIG


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "config.json"
        patcher = patch("src.config.config_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = Mock()
        network = patch("requests.get", side_effect=AssertionError("No network allowed"))
        network.start()
        self.addCleanup(network.stop)

    def write_config(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_missing_file_creates_defaults_in_selected_directory(self):
        config = Config(self.log)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), DEFAULT_CONFIG)
        self.assertEqual(config.weapon, "Vandal")
        self.assertTrue(config.get_table_flag("skin"))
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_nested_defaults_are_merged_and_unknown_keys_preserved(self):
        self.write_config({"cooldown": 7, "flags": {"game_chat": False, "custom": True},
                           "table": {"skin": False}, "custom_setting": {"secret": "private"}})
        config = Config(self.log)
        self.assertEqual(config.cooldown, 7)
        self.assertFalse(config.get_feature_flag("game_chat"))
        self.assertTrue(config.get_feature_flag("peak_rank_act"))
        self.assertTrue(config.get_feature_flag("custom"))
        self.assertFalse(config.get_table_flag("skin"))
        self.assertTrue(config.get_table_flag("winrate"))
        self.assertEqual(config.custom_setting, {"secret": "private"})
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["flags"], config.flags)
        self.assertEqual(saved["table"], config.table)
        self.assertNotIn("private", str(self.log.call_args_list))
        self.assertNotIn("secret", str(self.log.call_args_list))

    def test_defaults_are_independent_for_each_instance(self):
        original = deepcopy(DEFAULT_CONFIG)
        first = Config(self.log)
        second = Config(self.log)
        first.flags["game_chat"] = not original["flags"]["game_chat"]
        first.table["skin"] = not original["table"]["skin"]
        self.assertEqual(second.flags, original["flags"])
        self.assertEqual(second.table, original["table"])
        self.assertEqual(DEFAULT_CONFIG, original)
        self.assertIsNot(first.flags, second.flags)
        self.assertIsNot(second.flags, DEFAULT_CONFIG["flags"])

    def test_invalid_nested_types_are_replaced_with_defaults(self):
        for value in (None, [], "invalid", 4, False):
            with self.subTest(value=value):
                self.write_config({"flags": value, "table": value})
                config = Config(self.log)
                self.assertEqual(config.flags, DEFAULT_CONFIG["flags"])
                self.assertEqual(config.table, DEFAULT_CONFIG["table"])
                config.flags = value
                config.table = value
                self.assertEqual(config.get_feature_flag("game_chat"), DEFAULT_CONFIG["flags"]["game_chat"])
                self.assertEqual(config.get_table_flag("winrate"), DEFAULT_CONFIG["table"]["winrate"])

    def test_invalid_json_and_roots_are_backed_up_verbatim(self):
        for contents in ('{"private": invalid', "[]", "null", '"root"', "42"):
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                before = set(self.path.parent.glob("config.json.corrupt-*.bak"))
                config = Config(self.log)
                backups = set(self.path.parent.glob("config.json.corrupt-*.bak")) - before
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups.pop().read_text(encoding="utf-8"), contents)
                self.assertEqual(config.weapon, "Vandal")
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), DEFAULT_CONFIG)
        self.assertNotIn("private", str(self.log.call_args_list))

    def test_invalid_utf8_is_backed_up_as_bytes(self):
        invalid = b'{"private": "\xff"}'
        self.path.write_bytes(invalid)
        Config(self.log)
        backup, = self.path.parent.glob("config.json.corrupt-*.bak")
        self.assertEqual(backup.read_bytes(), invalid)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), DEFAULT_CONFIG)

    def test_backup_failure_keeps_original(self):
        invalid = '{"private": invalid'
        self.path.write_text(invalid, encoding="utf-8")
        with patch("src.config.shutil.copyfile", side_effect=PermissionError()):
            config = Config(self.log)
        self.assertEqual(self.path.read_text(encoding="utf-8"), invalid)
        self.assertEqual(config.weapon, "Vandal")

    def test_weapon_validation_is_offline_and_canonical(self):
        for value, expected in (("vandal", "Vandal"), ("PHANTOM", "Phantom"), (" sheriff ", "Sheriff"),
                                (None, "Vandal"), ([], "Vandal"), (123, "Vandal"), ("invalid", "Vandal")):
            with self.subTest(value=value):
                self.write_config({"weapon": value})
                config = Config(self.log)
                self.assertEqual(config.weapon, expected)
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["weapon"], expected)
        self.assertTrue(config.weapon_check("VaNdAl"))
        self.assertTrue(config.weapon_check("Melee"))
        self.assertFalse(config.weapon_check("invalid"))
        self.assertFalse(config.weapon_check(None))

    def test_config_dialog_returns_independent_defaults(self):
        config = Config(self.log)
        stream = io.StringIO()
        result = config.config_dialog(stream)
        self.assertEqual(json.loads(stream.getvalue()), DEFAULT_CONFIG)
        result["flags"]["game_chat"] = not DEFAULT_CONFIG["flags"]["game_chat"]
        self.assertEqual(config.flags, DEFAULT_CONFIG["flags"])

    def test_valid_complete_config_is_not_rewritten(self):
        self.write_config(DEFAULT_CONFIG)
        with patch("src.config.save_config") as save:
            Config(self.log)
        save.assert_not_called()

    def test_atomic_save_is_utf8_and_replaces_only_after_serialization(self):
        self.write_config({"old": True})
        original_replace = os.replace

        def check_replace(temporary, target):
            self.assertEqual(target, self.path)
            self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(json.loads(Path(temporary).read_text(encoding="utf-8")), {"name": "Привет"})
            original_replace(temporary, target)

        with patch("src.config.os.replace", side_effect=check_replace) as replace:
            save_config({"name": "Привет"})
        replace.assert_called_once()
        self.assertIn("Привет", self.path.read_text(encoding="utf-8"))
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_failed_save_leaves_original_and_removes_temporary(self):
        self.write_config({"old": True})
        for failure in (TypeError, PermissionError):
            with self.subTest(failure=failure):
                if failure is TypeError:
                    with self.assertRaises(TypeError):
                        save_config({"not_json": object()}, self.path)
                else:
                    with patch("src.config.os.replace", side_effect=PermissionError()):
                        with self.assertRaises(PermissionError):
                            save_config({"new": True}, self.path)
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"old": True})
                self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_save_failure_still_sets_instance_defaults(self):
        with patch("src.config.save_config", side_effect=PermissionError()):
            config = Config(self.log)
        self.assertEqual(config.weapon, "Vandal")
        self.assertEqual(config.table, DEFAULT_CONFIG["table"])

    def test_reload_only_reads_when_stat_signature_changes(self):
        config = Config(self.log)
        with patch("builtins.open", side_effect=AssertionError("Unchanged config must not be read")):
            self.assertFalse(config.reload_if_changed())
        save_config({"cooldown": 1234, "weapon": "phantom", "flags": {"game_chat": False}}, self.path)
        self.assertTrue(config.reload_if_changed())
        self.assertEqual(config.cooldown, 1234)
        self.assertEqual(config.weapon, "Phantom")
        self.assertFalse(config.get_feature_flag("game_chat"))
        self.assertEqual(config.table, DEFAULT_CONFIG["table"])
        self.assertFalse(config.reload_if_changed())

    def test_invalid_reload_retains_previous_and_does_not_overwrite(self):
        self.write_config({"cooldown": 4321, "weapon": "Phantom", "flags": {"game_chat": False}})
        config = Config(self.log)
        for invalid in ('{"private": broken', "null", "[]"):
            with self.subTest(invalid=invalid):
                self.path.write_text(invalid, encoding="utf-8")
                self.assertFalse(config.reload_if_changed())
                self.assertEqual(config.cooldown, 4321)
                self.assertEqual(config.weapon, "Phantom")
                self.assertFalse(config.get_feature_flag("game_chat"))
                self.assertEqual(self.path.read_text(encoding="utf-8"), invalid)
                with patch("builtins.open", side_effect=AssertionError("Already checked invalid config")):
                    self.assertFalse(config.reload_if_changed())
        self.path.unlink()
        self.assertFalse(config.reload_if_changed())
        self.assertEqual(config.cooldown, 4321)
        save_config({"cooldown": 10}, self.path)
        self.assertTrue(config.reload_if_changed())
        self.assertEqual(config.cooldown, 10)
        self.assertNotIn("private", str(self.log.call_args_list))


class ConfigPathTests(unittest.TestCase):
    def test_source_path_does_not_depend_on_working_directory(self):
        expected = Path(__file__).resolve().parents[1]
        with patch("src.config.sys.frozen", False, create=True), patch("os.getcwd", return_value="Z:/unrelated"):
            self.assertEqual(application_root(), expected)
            self.assertEqual(config_path(), expected / "config.json")

    def test_frozen_path_uses_executable_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "app.exe")
            with patch("src.config.sys.frozen", True, create=True), patch("src.config.sys.executable", executable):
                self.assertEqual(application_root(), Path(directory).resolve())
                self.assertEqual(config_path(), Path(directory).resolve() / "config.json")


if __name__ == "__main__":
    unittest.main()
