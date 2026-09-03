import os
import time
import json

class Stats:
    def __init__(self):
        pass

    def save_data(self, data):
        # path = os.path.join(os.getenv('APPDATA'), R'vry\stats.json')
        try:
            os.mkdir(os.path.join(os.getenv('APPDATA'), "vry"))
        except FileExistsError:
            pass
        try:
            with open(os.path.join(os.getenv('APPDATA'), "vry/stats.json"), "r") as f:
                original_data = json.load(f)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            original_data = {}

        updated_data = original_data.copy()
        for puuid in data.keys():
            if original_data.get(puuid) is None:
                updated_data.update({puuid: [data[puuid]]})
            else:
                updated_data[puuid].append(data[puuid])
        
        # updated_data.update(data)
        # print(updated_data)

        with open(os.path.join(os.getenv('APPDATA'), "vry/stats.json"), "w") as f:
            json.dump(updated_data, f)
    
    def read_data(self):
        try:
            with open(os.path.join(os.getenv('APPDATA'), "vry/stats.json"), "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            return {}

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
                    "winRate": entry.get("winRate"),
                    "earnedRR": entry.get("earnedRR"),
                    "team": entry.get("team"),
                    "epoch": entry.get("epoch", 0),
                }
        return sorted(matches.values(), key=lambda match: match["epoch"], reverse=True)[:limit]

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
        directory = os.path.join(os.getenv('APPDATA'), "vry")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "stats.json"), "w") as file:
            json.dump({}, file)

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
