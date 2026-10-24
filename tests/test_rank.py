import unittest
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError

from src.rank import Rank


def season(tier=15, rr=42, wins=3, games=5, tiers=None):
    return {
        "CompetitiveTier": tier,
        "RankedRating": rr,
        "LeaderboardRank": 123,
        "NumberOfWinsWithPlacements": wins,
        "NumberOfGames": games,
        "WinsByTier": tiers,
    }


def response(seasons=None, status=200):
    result = Mock(ok=status < 400, status_code=status, text="private response body")
    result.json.return_value = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": seasons}}}
    return result


class RankTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.log = Mock()
        self.content = Mock()
        self.content.get_act_episode_from_act_id.return_value = {"act": 2, "episode": 7}
        self.rank = Rank(self.client, self.log, self.content, ["old"])

    def test_current_and_previous_seasons_share_successful_response(self):
        self.client.fetch.return_value = response({"current": season(), "previous": season(21, 80, 4, 4)})
        current = self.rank.get_rank("player", "current")
        previous = self.rank.get_rank("player", "previous")
        self.assertEqual((current["rank"], current["rr"], current["leaderboard"], current["wr"]), (15, 42, 0, 60))
        self.assertEqual((previous["rank"], previous["rr"], previous["leaderboard"], previous["wr"]), (21, 80, 123, 100))
        self.client.fetch.assert_called_once_with("pd", "/mmr/v1/players/player", "get")

    def test_failed_and_missing_responses_are_safe_and_retried(self):
        for failed in (None, response(status=401), response(status=404), response(status=429), response(status=500)):
            with self.subTest(response=failed):
                self.rank.invalidate_cached_responses()
                self.client.fetch.reset_mock()
                self.client.fetch.side_effect = [failed, response({"current": season()})]
                result = self.rank.get_rank("player", "current")
                self.assertEqual(result["rank"], 0)
                self.assertEqual(result["rr"], 0)
                self.assertEqual(result["peakrank"], 0)
                self.assertEqual(result["numberofgames"], 0)
                self.assertEqual(result["wr"], "N/A")
                self.assertFalse(result["statusgood"])
                self.assertEqual(self.rank.get_rank("player", "current")["rank"], 15)
                self.assertEqual(self.client.fetch.call_count, 2)
        for call in self.log.call_args_list:
            self.assertNotIn("private response body", str(call))

    def test_connection_and_json_errors_do_not_become_cached(self):
        invalid = response()
        invalid.json.side_effect = ValueError("private malformed data")
        for failure in (ConnectionError("private connection data"), TimeoutError(), invalid):
            with self.subTest(failure=failure):
                self.rank.invalidate_cached_responses()
                self.client.fetch.side_effect = [failure, response({"current": season()})]
                self.assertFalse(self.rank.get_rank("player", "current")["statusgood"])
                self.assertFalse(self.rank.requestMap)
                self.assertEqual(self.rank.get_rank("player", "current")["rank"], 15)
        self.assertNotIn("private", str(self.log.call_args_list))

    def test_missing_seasons_and_malformed_shapes(self):
        for payload in (None, [], {}, {"QueueSkills": []}, {"QueueSkills": {"competitive": []}},
                        {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": []}}}):
            with self.subTest(payload=payload):
                self.rank.invalidate_cached_responses()
                self.client.fetch.return_value = response()
                self.client.fetch.return_value.json.return_value = payload
                result = self.rank.get_rank("player", "current")
                self.assertEqual(result["rank"], 0)
                self.assertEqual(result["wr"], "N/A")
                self.assertFalse(result["statusgood"])
                self.assertFalse(self.rank.requestMap)

    def test_absent_current_season_still_has_historical_peak(self):
        self.client.fetch.return_value = response({"old": season(tiers={"21": 1})})
        result = self.rank.get_rank("player", "current")
        self.assertEqual(result["rank"], 0)
        self.assertEqual(result["peakrank"], 24)
        self.assertEqual(result["wr"], "N/A")
        self.assertEqual((result["peakrankact"], result["peakrankep"]), (2, 7))
        self.content.get_act_episode_from_act_id.assert_called_once_with("old")

    def test_peak_adjusts_only_old_tiers_above_diamond(self):
        self.client.fetch.return_value = response({
            "current": season(tiers={"22": 5}), "old": season(tiers={"20": 1, "24": 1}),
            "malformed": None, "bad_tiers": season(tiers=["27"]),
        })
        result = self.rank.get_rank("player", "current")
        self.assertEqual(result["peakrank"], 27)
        self.content.get_act_episode_from_act_id.assert_called_with("old")

    def test_empty_seasons_zero_games_and_unranked(self):
        for seasons in (None, {}, {"current": None}, {"current": []}, {"current": season(2, 10, 0, 0)}):
            with self.subTest(seasons=seasons):
                self.rank.invalidate_cached_responses()
                self.client.fetch.return_value = response(seasons)
                result = self.rank.get_rank("player", "current")
                self.assertEqual((result["rank"], result["rr"], result["leaderboard"]), (0, 0, 0))
                self.assertEqual(result["wr"], "N/A")
                self.assertTrue(result["statusgood"])

    def test_numeric_strings_are_normalized(self):
        self.client.fetch.return_value = response({"current": season("24", "88", "3", "5", {"24": 1})})
        result = self.rank.get_rank("player", "current")
        self.assertEqual((result["rank"], result["rr"], result["wr"], result["numberofgames"]), (24, 88, 60, 5))

    def test_malformed_stats_use_numeric_defaults(self):
        for value in (None, [], {}, "invalid", -1, 1.5, True):
            with self.subTest(value=value):
                self.rank.invalidate_cached_responses()
                data = season(value, value, value, value, {"oops": 1, "99999": 2})
                data["LeaderboardRank"] = value
                self.client.fetch.return_value = response({"current": data})
                result = self.rank.get_rank("player", "current")
                self.assertEqual((result["rank"], result["rr"], result["peakrank"], result["numberofgames"]), (0, 0, 0, 0))
                self.assertEqual(result["wr"], "N/A")

    def test_invalid_wins_do_not_produce_false_percentages(self):
        for wins, games in ((6, 5), (None, 5), (-1, 5), (0, 0)):
            with self.subTest(wins=wins, games=games):
                self.rank.invalidate_cached_responses()
                self.client.fetch.return_value = response({"current": season(wins=wins, games=games)})
                self.assertEqual(self.rank.get_rank("player", "current")["wr"], "N/A")

    def test_missing_content_does_not_break_rank(self):
        self.client.fetch.return_value = response({"current": season()})
        self.content.get_act_episode_from_act_id.side_effect = KeyError("Seasons")
        result = self.rank.get_rank("player", "current")
        self.assertEqual(result["rank"], 15)
        self.assertIsNone(result["peakrankact"])

    def test_cache_expires_and_is_bounded_with_lru_eviction(self):
        self.rank.CACHE_MAX_ENTRIES = 2
        self.client.fetch.return_value = response({"current": season()})
        with patch("src.rank.time.monotonic", return_value=0):
            for player in ("a", "b", "a", "c"):
                self.rank.get_rank(player, "current")
        self.assertEqual(list(self.rank.requestMap), ["a", "c"])
        self.assertEqual(len(self.rank._cache_expirations), 2)
        self.assertEqual(self.client.fetch.call_count, 3)
        with patch("src.rank.time.monotonic", return_value=300):
            self.rank.get_rank("a", "previous")
        self.assertEqual(list(self.rank.requestMap), ["a"])
        self.assertEqual(self.client.fetch.call_count, 4)
        self.rank.invalidate_cached_responses()
        self.assertFalse(self.rank.requestMap)
        self.assertFalse(self.rank._cache_expirations)


if __name__ == "__main__":
    unittest.main()
