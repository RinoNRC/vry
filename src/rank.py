import time
from collections import OrderedDict

from requests.exceptions import RequestException


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _integer(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        number = int(value)
    except ValueError:
        return default
    return number if number >= 0 else default


def _seasons(payload):
    competitive = _mapping(_mapping(_mapping(payload).get("QueueSkills")).get("competitive"))
    if "SeasonalInfoBySeasonID" not in competitive:
        return None
    seasons = competitive["SeasonalInfoBySeasonID"]
    return {} if seasons is None else seasons if isinstance(seasons, dict) else None


class Rank:
    CACHE_TTL = 300
    CACHE_MAX_ENTRIES = 128

    def __init__(self, Requests, log, content, ranks_before):
        self.Requests = Requests
        self.log = log
        self.ranks_before = ranks_before
        self.content = content
        self.requestMap = OrderedDict()
        self._cache_expirations = {}

    def get_request(self, puuid):
        now = time.monotonic()
        for key in list(self.requestMap):
            if self._cache_expirations.get(key, 0) <= now:
                self.requestMap.pop(key, None)
                self._cache_expirations.pop(key, None)
        if puuid in self.requestMap:
            self.requestMap.move_to_end(puuid)
            return self.requestMap[puuid]

        try:
            response = self.Requests.fetch('pd', f"/mmr/v1/players/{puuid}", "get")
        except (RequestException, OSError, ValueError):
            self.log("Failed getting rank")
            return None
        try:
            cacheable = response is not None and response.ok and _seasons(response.json()) is not None
        except (AttributeError, TypeError, ValueError):
            cacheable = False
        if cacheable:
            self.requestMap[puuid] = response
            self._cache_expirations[puuid] = time.monotonic() + self.CACHE_TTL
            while len(self.requestMap) > self.CACHE_MAX_ENTRIES:
                key, _ = self.requestMap.popitem(last=False)
                self._cache_expirations.pop(key, None)
        return response

    def invalidate_cached_responses(self):
        self.requestMap.clear()
        self._cache_expirations.clear()

    def get_rank(self, puuid, seasonID):
        response = self.get_request(puuid)
        final = {
            "rank": 0,
            "rr": 0,
            "leaderboard": 0,
            "peakrank": 0,
            "wr": "N/A",
            "numberofgames": 0,
            "peakrankact": None,
            "peakrankep": None,
            "statusgood": bool(getattr(response, "ok", False)),
            "statuscode": getattr(response, "status_code", None),
        }
        if not final["statusgood"]:
            self.log("Failed getting rank")
            return final
        try:
            seasons = _seasons(response.json())
        except (AttributeError, TypeError, ValueError):
            seasons = None
        if seasons is None:
            final["statusgood"] = False
            self.log("Invalid rank data")
            return final

        current = _mapping(seasons.get(seasonID))
        tier = _integer(current.get("CompetitiveTier"))
        if 3 <= tier <= 27:
            final["rank"] = tier
            final["rr"] = _integer(current.get("RankedRating"))
            if tier >= 21:
                final["leaderboard"] = _integer(current.get("LeaderboardRank"))

        max_rank = final["rank"]
        max_rank_season = seasonID
        for season, stats in seasons.items():
            for tier in _mapping(_mapping(stats).get("WinsByTier")):
                tier = _integer(tier)
                if season in self.ranks_before and tier > 20:
                    tier += 3
                if max_rank < tier <= 27:
                    max_rank = tier
                    max_rank_season = season
        final["peakrank"] = max_rank

        wins = _integer(current.get("NumberOfWinsWithPlacements"), default=None)
        total_games = _integer(current.get("NumberOfGames"))
        final["numberofgames"] = total_games
        if total_games > 0 and wins is not None and wins <= total_games:
            final["wr"] = wins * 100 // total_games

        if max_rank_season is not None:
            try:
                peak = _mapping(self.content.get_act_episode_from_act_id(max_rank_season))
                final["peakrankact"] = peak.get("act")
                final["peakrankep"] = peak.get("episode")
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                pass
        return final


if __name__ == "__main__":
    from constants import before_ascendant_seasons, version, NUMBERTORANKS
    from requestsV import Requests
    from logs import Logging
    from errors import Error
    import urllib3
    import pyperclip
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    Logging = Logging()
    log = Logging.log

    ErrorSRC = Error(log)

    Requests = Requests(version, log, ErrorSRC)
    #custom region
    # Requests.pd_url = "https://pd.na.a.pvp.net"

    #season id
    s_id = "67e373c7-48f7-b422-641b-079ace30b427" 

    r = Rank(Requests, log, before_ascendant_seasons)

    res = r.get_rank("", s_id)
    print(res)
    #[[rank, rr, leadeboard, peak rank, wr,] status]
    # print(f"Rank: {res[0][0]} - {NUMBERTORANKS[res[0][0]]}\nPeak Rank: {res[0][3]} - {NUMBERTORANKS[res[0][3]]}\nRR: {res[0][1]}\nLeaderboard: {res[0][2]}\nStatus is good: {res[1]}\nWR: {res[0][4]}%")
