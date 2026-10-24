import time


class Names:
    CACHE_TTL = 300
    FAILURE_TTL = 15
    CACHE_LIMIT = 128

    def __init__(self, Requests, log):
        self.Requests = Requests
        self.log = log
        self._cache = {}
        self._retry_after = {}

    def clear_cache(self):
        self._cache.clear()
        self._retry_after.clear()

    def get_name_from_puuid(self, puuid):
        return self.get_multiple_names_from_puuid([puuid]).get(puuid, "Unknown")

    def get_multiple_names_from_puuid(self, puuids):
        puuids = list(dict.fromkeys(puuid for puuid in puuids if isinstance(puuid, str) and puuid))
        now = time.monotonic()
        self._cache = {key: value for key, value in self._cache.items() if value[0] > now}
        self._retry_after = {key: until for key, until in self._retry_after.items() if until > now}
        names = {puuid: self._cache.get(puuid, (0, "Unknown"))[1] for puuid in puuids}
        missing = [puuid for puuid in puuids if puuid not in self._cache and puuid not in self._retry_after]
        if not missing:
            return names
        for puuid in missing:
            self._retry_after[puuid] = now + self.FAILURE_TTL
        try:
            response = self.Requests.fetch("pd", "/name-service/v2/players", "put", json=missing)
            payload = response.json() if response is not None and response.status_code == 200 else None
            if not isinstance(payload, list):
                return names
            for player in payload:
                if not isinstance(player, dict) or player.get("Subject") not in missing:
                    continue
                subject = player["Subject"]
                game_name, tag = player.get("GameName"), player.get("TagLine")
                if not isinstance(game_name, str) or not game_name or not isinstance(tag, str):
                    continue
                name = f"{game_name}#{tag}" if tag else game_name
                self._cache[subject] = (now + self.CACHE_TTL, name)
                self._retry_after.pop(subject, None)
                names[subject] = name
        except Exception as exc:
            self.log(f"Player names unavailable ({type(exc).__name__})")
        while len(self._cache) > self.CACHE_LIMIT:
            del self._cache[next(iter(self._cache))]
        while len(self._retry_after) > self.CACHE_LIMIT:
            del self._retry_after[next(iter(self._retry_after))]
        return names

    def get_names_from_puuids(self, players):
        return self.get_multiple_names_from_puuid(self.get_players_puuid(players))

    def get_players_puuid(self, players):
        return [player["Subject"] for player in (players or []) if isinstance(player, dict) and player.get("Subject")]
