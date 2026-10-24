import math
import threading
import time

from src.party import normalize_party_id


class PlayerStats:
    def __init__(self, Requests, log, config):
        self.Requests = Requests
        self.log = log
        self.config = config
        self.match_details_cache = {}
        self._retry_after = {}
        self._lock = threading.RLock()

    def clear_runtime_cache(self):
        with self._lock:
            self.match_details_cache.clear()
            self._retry_after.clear()

    def invalidate_match(self, match_id):
        with self._lock:
            self.match_details_cache.pop(match_id, None)
            self._retry_after.pop(match_id, None)

    def _default_stats(self):
        return {
            "kd": "N/A", "hs": "N/A",
            "kills": "N/A", "deaths": "N/A", "assists": "N/A", "adr": "N/A",
            "RankedRatingEarned": "N/A", "AFKPenalty": "N/A",
        }

    @staticmethod
    def _number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0

    def _get_match_details_cached(self, match_id):
        if not match_id:
            return None
        with self._lock:
            if match_id in self.match_details_cache:
                return self.match_details_cache[match_id]
            if time.monotonic() < self._retry_after.get(match_id, 0):
                return None
            # Failed/incomplete results are retried, not cached as final statistics.
            now = time.monotonic()
            self._retry_after = {key: until for key, until in self._retry_after.items() if until > now}
            self._retry_after[match_id] = now + 15
            if len(self._retry_after) > 128:
                del self._retry_after[next(iter(self._retry_after))]
            response = self.Requests.fetch(
                "pd", f"/match-details/v1/matches/{match_id}", "get"
            )
            if response is None or response.status_code != 200:
                return None
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("players"), list):
                return None
            info = data.get("matchInfo", data.get("gameInfo"))
            if not isinstance(info, dict) or info.get("isCompleted") is not True:
                return None
            if info.get("matchId") != match_id:
                return None
            players = data["players"]
            if not players or not all(
                isinstance(player, dict)
                and player.get("subject")
                and isinstance(player.get("stats"), dict)
                and all(self._number(player["stats"].get(key)) for key in ("kills", "deaths", "assists"))
                for player in players
            ):
                return None
            self.match_details_cache[match_id] = data
            # Keep the cache bounded during long sessions/backfills.
            if len(self.match_details_cache) > 60:
                del self.match_details_cache[next(iter(self.match_details_cache))]
            self._retry_after.pop(match_id, None)
            return data

    def get_match_stats(self, match_id):
        """Return (availability, stats by subject) for this exact match only."""
        try:
            data = self._get_match_details_cached(match_id)
            if data is None:
                return "pending", {}
            return "ready", {
                player["subject"]: self._process_match_data(player["subject"], data, {}) | {
                    "partyId": normalize_party_id(player.get("partyId")),
                    "partyResolved": True,
                }
                for player in data["players"]
            }
        except Exception as exc:
            # No tokens, response bodies or private session data in diagnostics.
            self.log(f"Match statistics unavailable ({type(exc).__name__}); will retry")
            return "unavailable", {}

    def get_stats(self, puuid, target_match_id=None):
        # Visibility of table columns must not disable collection for history.
        if target_match_id:
            _, players = self.get_match_stats(target_match_id)
            return players.get(puuid, self._default_stats())
        try:
            response = self.Requests.fetch(
                "pd",
                f"/mmr/v1/players/{puuid}/competitiveupdates?startIndex=0&endIndex=1&queue=competitive",
                "get",
            )
            if response is None or response.status_code != 200:
                return self._default_stats()
            matches = response.json().get("Matches", [])
            if not matches or not matches[0].get("MatchID"):
                return self._default_stats()
            summary = matches[0]
            data = self._get_match_details_cached(summary["MatchID"])
            if data is not None:
                return self._process_match_data(puuid, data, summary)
        except Exception as exc:
            self.log(f"Player statistics unavailable ({type(exc).__name__})")
        return self._default_stats()

    def iter_recent_stats(self, puuid, limit=20, exclude_match_id=None, should_stop=None):
        limit = max(1, min(20, int(limit)))
        should_stop = should_stop or (lambda: False)
        result = self._default_stats() | {
            "status": "loading", "matches": 0,
            "requestedMatches": limit, "availableMatches": 0,
            "hsMatches": 0, "adrMatches": 0,
        }
        if should_stop():
            return
        try:
            request_limit = limit + (1 if exclude_match_id else 0)
            response = self.Requests.fetch(
                "pd",
                f"/mmr/v1/players/{puuid}/competitiveupdates?startIndex=0&endIndex={request_limit}&queue=competitive",
                "get",
            )
            if response is None or response.status_code != 200:
                yield result | {"status": "unavailable"}
                return
            payload = response.json()
            summaries = payload.get("Matches") if isinstance(payload, dict) else None
            if not isinstance(summaries, list):
                yield result | {"status": "unavailable"}
                return
        except Exception as exc:
            self.log(f"Recent statistics unavailable ({type(exc).__name__})")
            yield result | {"status": "unavailable"}
            return

        match_ids = []
        for summary in summaries:
            match_id = summary.get("MatchID") if isinstance(summary, dict) else None
            if match_id and match_id != exclude_match_id and match_id not in match_ids:
                match_ids.append(match_id)
            if len(match_ids) == limit:
                break
        result["availableMatches"] = len(match_ids)
        if limit == 1 and match_ids:
            summary = next(item for item in summaries if isinstance(item, dict) and item.get("MatchID") == match_ids[0])
            result["matchId"] = match_ids[0]
            result["RankedRatingEarned"] = summary.get("RankedRatingEarned", "N/A")
            result["AFKPenalty"] = summary.get("AFKPenalty", "N/A")
        if not match_ids:
            yield result | {"status": "empty"}
            return
        yield dict(result)

        kills = deaths = assists = hits = headshots = damage = rounds = 0
        hit_matches = damage_matches = 0
        for index, match_id in enumerate(match_ids):
            if should_stop():
                return
            try:
                data = self._get_match_details_cached(match_id)
                stats = self._process_match_data(puuid, data, {}) if data else self._default_stats()
                if all(self._number(stats.get(key)) for key in ("kills", "deaths", "assists")):
                    match_hits, match_heads, match_damage, match_rounds, has_hits, has_damage = self._hit_totals(puuid, data)
                    result["matches"] += 1
                    kills += stats["kills"]
                    deaths += stats["deaths"]
                    assists += stats["assists"]
                    hits += match_hits
                    headshots += match_heads
                    if has_hits:
                        hit_matches += 1
                    if has_damage:
                        damage += match_damage
                        rounds += match_rounds
                        damage_matches += 1
                    result.update({
                        "kills": kills, "deaths": deaths, "assists": assists,
                        "kd": round(kills / deaths, 2) if deaths else kills,
                        "hs": round(headshots / hits * 100) if hit_matches and hits else "N/A",
                        "adr": round(damage / rounds, 1) if damage_matches and rounds else "N/A",
                        "hsMatches": hit_matches, "adrMatches": damage_matches,
                    })
            except Exception as exc:
                self.log(f"Recent match statistics unavailable ({type(exc).__name__})")
            if should_stop():
                return
            if index == len(match_ids) - 1:
                result["status"] = "ready" if result["matches"] == len(match_ids) else "partial" if result["matches"] else "unavailable"
            yield dict(result)

    @staticmethod
    def _hit_totals(puuid, match_data):
        total_hits, headshots, damage, rounds = 0, 0, 0, 0
        has_hits, has_damage = False, False
        for round_data in match_data.get("roundResults") or []:
            for entry in round_data.get("playerStats") or []:
                if entry.get("subject") != puuid:
                    continue
                rounds += 1
                for hit in entry.get("damage") or []:
                    if all(PlayerStats._number(hit.get(key)) for key in ("legshots", "bodyshots", "headshots")):
                        total_hits += hit["legshots"] + hit["bodyshots"] + hit["headshots"]
                        headshots += hit["headshots"]
                        has_hits = True
                    if PlayerStats._number(hit.get("damage")):
                        damage += hit["damage"]
                        has_damage = True
        return total_hits, headshots, damage, rounds, has_hits, has_damage

    def _process_match_data(self, puuid, match_data, match_summary):
        result = self._default_stats()
        player = next((p for p in match_data.get("players", []) if p.get("subject") == puuid), None)
        if player is None or not isinstance(player.get("stats"), dict):
            return result
        stats = player["stats"]
        for key in ("kills", "deaths", "assists"):
            if self._number(stats.get(key)):
                result[key] = stats[key]
        kills, deaths = result["kills"], result["deaths"]
        if self._number(kills) and self._number(deaths):
            result["kd"] = round(kills / deaths, 2) if deaths else kills

        total_hits, headshots, damage, rounds, has_hits, has_damage = self._hit_totals(puuid, match_data)
        if has_hits and total_hits:
            result["hs"] = round(headshots / total_hits * 100)
        if has_damage and rounds:
            result["adr"] = round(damage / rounds, 1)
        result["RankedRatingEarned"] = match_summary.get("RankedRatingEarned", "N/A")
        result["AFKPenalty"] = match_summary.get("AFKPenalty", "N/A")
        return result
