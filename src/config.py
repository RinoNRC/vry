import json
import os
import shutil
import sys
import tempfile
from copy import deepcopy
from io import TextIOWrapper
from pathlib import Path
from uuid import uuid4

from src.constants import DEFAULT_CONFIG, WEAPONS


def application_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path():
    return application_root() / "config.json"


def save_config(config, path=None):
    path = Path(path) if path is not None else config_path()
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _merge_defaults(defaults, values):
    result = deepcopy(values) if isinstance(values, dict) else {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            result[key] = _merge_defaults(value, result.get(key))
        elif key not in result:
            result[key] = deepcopy(value)
    return result


def _canonical_weapon(name):
    if isinstance(name, str):
        return next((weapon for weapon in WEAPONS if weapon.casefold() == name.strip().casefold()), None)
    return None


def apply_defaults(cls):
    for name, value in DEFAULT_CONFIG.items():
        setattr(cls, name, deepcopy(value))
    return cls


@apply_defaults
class Config:
    def __init__(self, log):
        self.log = log
        path = config_path()
        config = {}
        should_save = False
        try:
            with open(path, "r", encoding="utf-8") as file:
                config = json.load(file)
            if not isinstance(config, dict):
                raise ValueError("Configuration root must be an object")
            should_save = True
        except FileNotFoundError:
            log("config.json not found, creating new one")
            should_save = True
        except (ValueError, UnicodeError):
            backup = path.with_name(path.name + ".corrupt-" + uuid4().hex + ".bak")
            try:
                shutil.copyfile(path, backup)
            except OSError:
                log("Could not back up invalid config.json; leaving the original unchanged")
            else:
                log("Invalid config.json preserved in a backup; restoring defaults")
                should_save = True
            config = {}
        except OSError:
            log("Could not read config.json; using defaults without overwriting it")

        normalized = _merge_defaults(DEFAULT_CONFIG, config)
        normalized["weapon"] = _canonical_weapon(normalized.get("weapon")) or DEFAULT_CONFIG["weapon"]
        if should_save and (not path.exists() or normalized != config):
            try:
                save_config(normalized, path)
            except OSError:
                log("Could not save config.json; using settings in memory")
        for name, value in normalized.items():
            setattr(self, name, value)
        self._config_signature = self._file_signature(path)

    @staticmethod
    def _file_signature(path):
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def reload_if_changed(self):
        path = config_path()
        signature = self._file_signature(path)
        if signature == self._config_signature:
            return False
        self._config_signature = signature
        try:
            with open(path, "r", encoding="utf-8") as file:
                config = json.load(file)
            if not isinstance(config, dict):
                raise ValueError("Configuration root must be an object")
        except (OSError, ValueError, UnicodeError):
            self.log("Could not reload config.json; keeping previous settings")
            return False
        normalized = _merge_defaults(DEFAULT_CONFIG, config)
        normalized["weapon"] = _canonical_weapon(normalized.get("weapon")) or DEFAULT_CONFIG["weapon"]
        for name, value in normalized.items():
            setattr(self, name, value)
        self._config_signature = signature
        return True

    def get_feature_flag(self, key):
        flags = self.__dict__.get("flags")
        if not isinstance(flags, dict):
            flags = {}
        return flags.get(key, DEFAULT_CONFIG["flags"].get(key))

    def get_table_flag(self, key):
        table = self.__dict__.get("table")
        if not isinstance(table, dict):
            table = {}
        return table.get(key, DEFAULT_CONFIG["table"].get(key))

    def config_dialog(self, fileToWrite: TextIOWrapper):
        config = deepcopy(DEFAULT_CONFIG)
        json.dump(config, fileToWrite, indent=4, ensure_ascii=False)
        return config

    def weapon_check(self, name):
        return _canonical_weapon(name) is not None
