import unittest
from unittest.mock import Mock

from src.app_state import AppStateStore
from src.player_stats import PlayerStats


class StateReliabilityTests(unittest.TestCase):
    def test_disconnect_clears_private_context_and_ignores_old_results(self):
        store = AppStateStore()
        store.publish("heartbeat", {"state": "INGAME", "matchId": "m", "puuid": "self", "players": {"self": {"puuid": "self"}}})
        store.publish("chat", {"body": "private"})
        store.publish("matchLoadout", {"Players": {"self": {"Name": "Private"}}})
        store.publish("disconnected", {})
        store.publish("recentStats", {"accountPuuid": "self", "matchId": "m", "state": "INGAME", "puuid": "self", "stats": {"kd": 2}})
        snapshot = store.snapshot()
        self.assertEqual(snapshot["status"], "DISCONNECTED")
        for key in ("heartbeat", "account", "loadouts"):
            self.assertEqual(snapshot[key], {})
        self.assertEqual(snapshot["chat"], [])

    def test_latest_match_rr_is_published_without_overwriting_match_totals(self):
        store = AppStateStore()
        store.publish("heartbeat", {"state": "INGAME", "matchId": "m", "puuid": "self", "players": {"self": {"puuid": "self", "kills": "N/A"}}})
        store.publish("recentStats", {
            "accountPuuid": "self", "matchId": "m", "state": "INGAME", "puuid": "self",
            "stats": {"requestedMatches": 1, "RankedRatingEarned": 17, "AFKPenalty": 0, "kd": 2, "hs": 30, "kills": 20},
        })
        player = store.snapshot()["heartbeat"]["players"]["self"]
        self.assertEqual(player["earnedRR"], 17)
        self.assertEqual(player["afkPenalty"], 0)
        self.assertEqual(player["kills"], "N/A")

    def test_invalid_numbers_are_not_statistics(self):
        for value in (True, -1, float("nan"), float("inf"), "2", None):
            self.assertFalse(PlayerStats._number(value))
        for value in (0, 1, 1.5):
            self.assertTrue(PlayerStats._number(value))

    def test_latest_one_match_exposes_rr_without_extra_requests(self):
        client = Mock()
        summary = Mock(status_code=200)
        summary.json.return_value = {"Matches": [{"MatchID": "done", "RankedRatingEarned": 20, "AFKPenalty": 0}]}
        detail = Mock(status_code=200)
        detail.json.return_value = {"matchInfo": {"matchId": "done", "isCompleted": True}, "players": [{"subject": "self", "stats": {"kills": 12, "deaths": 6, "assists": 2}}]}
        client.fetch.side_effect = [summary, detail]
        results = list(PlayerStats(client, Mock(), Mock()).iter_recent_stats("self", limit=1))
        self.assertEqual(results[-1]["matchId"], "done")
        self.assertEqual(results[-1]["RankedRatingEarned"], 20)
        self.assertEqual(results[-1]["AFKPenalty"], 0)
        self.assertEqual(client.fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
