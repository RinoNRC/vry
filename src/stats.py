import os
import time
import json
import shutil
import tempfile
import threading

from src.party import history_party_labels, normalize_party_id


class Stats:
    _lock = threading.RLock()
    STAT_FIELDS = ("hs", "kd", "kills", "deaths", "assists", "adr")

    def __init__(self):
        self.path = os.path.join(os.getenv("APPDATA"), "vry", "stats.json")

    @staticmethod
    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _read_data(self):
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not all(isinstance(entries, list) for entries in data.values()):
                raise ValueError("Invalid history format")
            return data
        except FileNotFoundError:
            return {}

    def _write_data(self, data):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        # Preserve the original before the first mutation, including backfills.
        backup = self.path + ".bak"
        if os.path.exists(self.path) and not os.path.exists(backup):
            shutil.copy2(self.path, backup)
        fd, temporary = tempfile.mkstemp(prefix="stats-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_data(self, data):
        with self._lock:
            original = self._read_data()
            for puuid, entry in data.items():
                entries = original.setdefault(puuid, [])
                existing = next((item for item in entries if entry.get("match_id") and item.get("match_id") == entry["match_id"]), None)
                if existing is None:
                    entries.append(entry)
            self._write_data(original)

    def read_data(self):
        with self._lock:
            try:
                return self._read_data()
            except (OSError, ValueError):
                return {}

    def get_incomplete_matches(self, limit=30):
        matches = {}
        data = self.read_data()
        recent = {}
        for entries in data.values():
            for entry in entries:
                match_id = entry.get("match_id")
                if match_id:
                    recent[match_id] = max(recent.get(match_id, 0), entry.get("epoch", 0))
        party_candidates = set(sorted(recent, key=recent.get, reverse=True)[:limit])
        for puuid, entries in data.items():
            for entry in entries:
                match_id = entry.get("match_id")
                needs_stats = not entry.get("statsResolved") and any(
                    not self._is_number(entry.get(field)) for field in self.STAT_FIELDS
                )
                needs_party = match_id in party_candidates and entry.get("partyResolved") is not True
                if match_id and (needs_stats or needs_party):
                    match = matches.setdefault(match_id, {"epoch": 0, "players": set()})
                    match["epoch"] = max(match["epoch"], entry.get("epoch", 0))
                    match["players"].add(puuid)
        return dict(sorted(matches.items(), key=lambda item: item[1]["epoch"], reverse=True)[:limit])

    def update_match_stats(self, match_id, players):
        changed = False
        with self._lock:
            data = self._read_data()
            for puuid, values in players.items():
                for entry in data.get(puuid, []):
                    if entry.get("match_id") != match_id:
                        continue
                    for field in self.STAT_FIELDS:
                        value = values.get(field)
                        if self._is_number(value) and entry.get(field) != value:
                            entry[field] = value
                            changed = True
                    if values.get("partyResolved") is True:
                        party_id = normalize_party_id(values.get("partyId"))
                        if party_id is None and entry.get("partyResolved") is True:
                            party_id = normalize_party_id(entry.get("partyId"))
                        if entry.get("partyId") != party_id or "partyId" not in entry:
                            entry["partyId"] = party_id
                            changed = True
                        if entry.get("partyResolved") is not True:
                            entry["partyResolved"] = True
                            changed = True
                    # Missing hit data is legitimate in some modes. Do not retry
                    # forever once all core player totals have been published.
                    resolved = all(self._is_number(values.get(field)) for field in ("kills", "deaths", "assists"))
                    if resolved and not entry.get("statsResolved"):
                        entry["statsResolved"] = True
                        changed = True
            if changed:
                self._write_data(data)
        return changed

    def get_history(self, limit=30):
        matches = {}
        for puuid, entries in self.read_data().items():
            for entry in entries:
                match_id = entry.get("match_id")
                if not match_id:
                    continue
                match = matches.setdefault(match_id, {
                    "match_id": match_id,
                    "epoch": 0,
                    "map": "Unknown",
                    "mapSplash": None,
                    "mode": None,
                    "server": None,
                    "account_puuid": None,
                    "players": {},
                })
                match["epoch"] = max(match["epoch"], entry.get("epoch", 0))
                map_value = entry.get("map", "Unknown")
                if isinstance(map_value, dict):
                    map_name = map_value.get("name", "Unknown")
                    map_splash = map_value.get("splash")
                else:
                    map_name = map_value
                    map_splash = None
                if map_name not in (None, "", "N/A", "Unknown"):
                    match["map"] = map_name
                if map_splash:
                    match["mapSplash"] = map_splash
                match["mode"] = entry.get("mode") or match["mode"]
                match["server"] = entry.get("server") or match["server"]
                match["account_puuid"] = entry.get("account_puuid") or match["account_puuid"]
                match["players"][puuid] = {
                    "puuid": puuid,
                    "name": entry.get("name", "Unknown"),
                    "agent": entry.get("agent", "Unknown"),
                    "rank": entry.get("rank", 0),
                    "rr": entry.get("rr", 0),
                    "hs": entry.get("hs"),
                    "kd": entry.get("kd"),
                    "kills": entry.get("kills"),
                    "deaths": entry.get("deaths"),
                    "assists": entry.get("assists"),
                    "adr": entry.get("adr"),
                    "winRate": entry.get("winRate"),
                    "earnedRR": entry.get("earnedRR"),
                    "team": entry.get("team"),
                    "epoch": entry.get("epoch", 0),
                    "partyId": normalize_party_id(entry.get("partyId")),
                    "partyResolved": entry.get("partyResolved") is True,
                    "partySource": "match-results" if entry.get("partyResolved") is True else None,
                    "partyNumber": 0,
                    "partySize": 0,
                }
        history = sorted(matches.values(), key=lambda match: match["epoch"], reverse=True)[:limit]
        for match in history:
            for puuid, label in history_party_labels(match["players"]).items():
                match["players"][puuid].update(label)
        return history

    def get_encounters(self):
        encounters = {}
        for puuid, entries in self.read_data().items():
            unique_matches = {}
            for entry in entries:
                match_id = entry.get("match_id")
                if match_id and match_id not in unique_matches:
                    unique_matches[match_id] = entry
            if not unique_matches:
                continue
            latest = max(unique_matches.values(), key=lambda entry: entry.get("epoch", 0))
            encounters[puuid] = {
                "count": len(unique_matches),
                "lastSeenAt": latest.get("epoch", 0),
                "lastAgent": latest.get("agent", "Unknown"),
                "lastName": latest.get("name", "Unknown"),
            }
        return encounters

    def get_player_history(self, puuid, limit=20):
        entries = self.read_data().get(puuid, [])
        return sorted(entries, key=lambda entry: entry.get("epoch", 0), reverse=True)[:limit]

    def clear_data(self):
        with self._lock:
            self._write_data({})

    def convert_time(self, s):
        s = int(s)
        if s < 60:
            if s == 1:
                return f"{s} second"
            else:
                return f"{s} seconds"
        elif s < 3600:
            if s // 60 == 1:
                return f"{s // 60} minute"
            else:
                return f"{s // 60} minutes"
        elif s < 86400:
            if s // 3600 == 1:
                return f"{s // 3600} hours"
            else:
                return f"{s // 3600} hours"
        else:
            if s // 86400 == 1:
                return f"{s // 86400} days"
            else:
                return f"{s // 86400} days"
