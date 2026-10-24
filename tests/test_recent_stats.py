import copy
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from src.app_state import AppStateStore
from src.player_stats import PlayerStats
from src.recent_stats_sync import RecentStatsSync
from src.stat_format import recent_stats_caption


def response(payload, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    return result


def details(match_id, kills=12, deaths=6, head=2, body=3):
    return {
        "matchInfo": {"matchId": match_id, "isCompleted": True},
        "players": [{"subject": "a", "stats": {"kills": kills, "deaths": deaths, "assists": 3}}],
        "roundResults": [{"playerStats": [{
            "subject": "a", "damage": [{
                "headshots": head, "bodyshots": body, "legshots": 0, "damage": 300,
            }],
        }]}],
    }


class RecentStatsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.stats = PlayerStats(self.client, Mock(), Mock())

    def history(self, *match_ids):
        return response({"Matches": [{"MatchID": match_id} for match_id in match_ids]})

    def test_weighted_totals_not_mean_of_percentages_or_ratios(self):
        self.client.fetch.side_effect = [
            self.history("one", "two"),
            response(details("one", kills=12, deaths=6, head=2, body=3)),
            response(details("two", kills=8, deaths=14, head=1, body=14)),
        ]
        results = list(self.stats.iter_recent_stats("a"))
        self.assertEqual([r["matches"] for r in results], [0, 1, 2])
        self.assertEqual([r["status"] for r in results], ["loading", "loading", "ready"])
        final = results[-1]
        self.assertEqual(final["kd"], 1)
        self.assertEqual(final["hs"], 15)
        self.assertEqual(final["adr"], 300)
        self.assertEqual(final["assists"], 6)
        self.assertEqual(final["requestedMatches"], 20)
        self.assertEqual(final["availableMatches"], 2)
        self.assertEqual(final["RankedRatingEarned"], "N/A")
        self.assertEqual(results[0]["kd"], "N/A")
        self.assertIn("endIndex=20&queue=competitive", self.client.fetch.call_args_list[0].args[1])

    def test_active_match_and_duplicate_summaries_are_excluded(self):
        self.client.fetch.side_effect = [
            self.history("active", "one", "one"), response(details("one")),
        ]
        result = list(self.stats.iter_recent_stats("a", exclude_match_id="active"))[-1]
        self.assertEqual(result["matches"], 1)
        self.assertEqual(self.client.fetch.call_count, 2)
        self.assertEqual(self.client.fetch.call_args.args[1], "/match-details/v1/matches/one")

    def test_excluded_active_match_does_not_shrink_twenty_match_sample(self):
        ids = [f"m{i}" for i in range(20)]
        self.client.fetch.side_effect = [self.history("active", *ids)] + [response(details(m)) for m in ids]
        final = list(self.stats.iter_recent_stats("a", exclude_match_id="active"))[-1]
        self.assertEqual(final["matches"], 20)
        self.assertIn("endIndex=21", self.client.fetch.call_args_list[0].args[1])

    def test_match_info_is_authoritative_and_must_be_complete(self):
        for change in ({"isCompleted": False}, {"matchId": "wrong"}, {"isCompleted": None}):
            self.stats.clear_runtime_cache()
            data = details("one")
            data["gameInfo"] = {"matchId": "one", "isCompleted": True}
            data["matchInfo"].update(change)
            self.client.fetch.return_value = response(data)
            self.assertEqual(self.stats.get_match_stats("one"), ("pending", {}))

    def test_headshot_sample_is_reported_separately(self):
        no_hits = details("two")
        no_hits.pop("roundResults")
        self.client.fetch.side_effect = [self.history("one", "two"), response(details("one")), response(no_hits)]
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["matches"], 2)
        self.assertEqual(final["hsMatches"], 1)
        self.assertIn("для HS%: 1", recent_stats_caption({"recentStats": final}))

    def test_twenty_match_limit(self):
        ids = [f"m{i}" for i in range(30)]
        self.client.fetch.side_effect = [self.history(*ids)] + [response(details(m)) for m in ids]
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["matches"], 20)
        self.assertEqual(self.client.fetch.call_count, 21)

    def test_partial_results_retry_missing_details_and_reuse_cached_matches(self):
        self.client.fetch.side_effect = [self.history("one", "two"), response(details("one")), response({}, 404)]
        result = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["matches"], 1)
        self.assertEqual(result["kd"], 2)
        self.stats._retry_after.clear()
        self.client.fetch.side_effect = [self.history("one", "two"), response(details("two"))]
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["status"], "ready")
        self.assertEqual(final["matches"], 2)
        self.assertEqual(self.client.fetch.call_count, 5)

    def test_missing_player_and_unfinished_games_are_not_zero_stats(self):
        missing = details("missing")
        missing["players"][0]["subject"] = "other"
        unfinished = details("unfinished")
        unfinished["matchInfo"]["isCompleted"] = False
        self.client.fetch.side_effect = [self.history("missing", "unfinished"), response(missing), response(unfinished)]
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["status"], "unavailable")
        self.assertEqual(final["matches"], 0)
        self.assertEqual(final["hs"], "N/A")
        self.assertEqual(final["kd"], "N/A")

    def test_zero_deaths_and_missing_hit_data(self):
        data = details("one", deaths=0)
        data.pop("roundResults")
        self.client.fetch.side_effect = [self.history("one"), response(data)]
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["kd"], 12)
        self.assertEqual(final["hs"], "N/A")
        self.assertEqual(final["adr"], "N/A")
        self.assertEqual(final["status"], "ready")

    def test_empty_history(self):
        self.client.fetch.return_value = self.history()
        final = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(final["status"], "empty")
        self.assertEqual(final["kd"], "N/A")
        self.assertEqual(self.client.fetch.call_count, 1)

    def test_bad_history_responses(self):
        for payload, status in (({}, 200), ({"Matches": None}, 200), ([], 200), ({}, 403), ({}, 429)):
            with self.subTest(payload=payload, status=status):
                self.client.fetch.return_value = response(payload, status)
                result = list(self.stats.iter_recent_stats("a"))[-1]
                self.assertEqual(result["status"], "unavailable")

    def test_connection_error(self):
        self.client.fetch.side_effect = TimeoutError("private data")
        result = list(self.stats.iter_recent_stats("a"))[-1]
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private data", str(self.stats.log.call_args_list))

    def test_cancellation_before_and_between_requests(self):
        self.assertEqual(list(self.stats.iter_recent_stats("a", should_stop=lambda: True)), [])
        self.client.fetch.assert_not_called()
        self.client.fetch.return_value = self.history("one")
        stopped = False
        iterator = self.stats.iter_recent_stats("a", should_stop=lambda: stopped)
        next(iterator)
        stopped = True
        self.assertEqual(list(iterator), [])
        self.assertEqual(self.client.fetch.call_count, 1)


class RecentStatsStateTests(unittest.TestCase):
    def setUp(self):
        self.state = AppStateStore()
        self.heartbeat = {
            "puuid": "a", "matchId": "active", "state": "INGAME",
            "players": {"a": {"puuid": "a", "kd": "N/A", "headshotPercentage": "N/A", "kills": "N/A"}},
        }
        self.event = {
            "accountPuuid": "a", "matchId": "active", "state": "INGAME", "puuid": "a",
            "stats": {"status": "ready", "matches": 20, "availableMatches": 20, "hs": 25, "kd": 1.2, "kills": 300},
        }
        self.state.publish("heartbeat", self.heartbeat)

    def test_enrichment_updates_ui_and_account_without_changing_match_totals_or_time(self):
        before = self.state.snapshot()
        self.state.publish("recentStats", self.event)
        after = self.state.snapshot()
        player = after["heartbeat"]["players"]["a"]
        self.assertEqual(player["kd"], 1.2)
        self.assertEqual(player["headshotPercentage"], 25)
        self.assertEqual(player["kills"], "N/A")
        self.assertEqual(self.heartbeat["players"]["a"]["kd"], "N/A")
        self.assertEqual(after["account"]["profile"]["kd"], 1.2)
        self.assertGreater(after["revision"], before["revision"])
        self.assertEqual(after["history_revision"], before["history_revision"])
        self.assertEqual(after["heartbeat_at"], before["heartbeat_at"])
        self.assertEqual(after["heartbeat_history"], before["heartbeat_history"])

    def test_worker_to_state_integration_keeps_history_separate(self):
        responses = iter([
            response({"Matches": [{"MatchID": "finished"}]}),
            response(details("finished")),
        ])
        client = SimpleNamespace(headers={}, lockfile={}, fetch=lambda *args, **kwargs: next(responses))
        worker = RecentStatsSync(client, Mock(), self.state, Mock())
        worker.submit(self.heartbeat)
        worker.process_once(now=0)
        worker.process_once(now=1)
        worker.stop()
        snapshot = self.state.snapshot()
        player = snapshot["heartbeat"]["players"]["a"]
        self.assertEqual(player["headshotPercentage"], 40)
        self.assertEqual(player["kd"], 2)
        self.assertEqual(player["recentStats"]["matches"], 1)
        self.assertEqual(player["recentStats"]["status"], "ready")
        self.assertEqual(player["kills"], "N/A")
        self.assertEqual(snapshot["history_revision"], 0)

    def test_full_lobby_fetches_only_latest_match_for_each_player(self):
        ids = [f"p{i}" for i in range(10)]
        heartbeat = self.heartbeat | {
            "puuid": ids[0],
            "players": {puuid: {"puuid": puuid, "kills": "N/A"} for puuid in ids},
        }
        calls = []

        def fetch(kind, endpoint, method):
            calls.append(endpoint)
            if "/competitiveupdates?" in endpoint:
                self.assertIn("endIndex=2&queue=competitive", endpoint)
                puuid = endpoint.split("/players/", 1)[1].split("/", 1)[0]
                return response({"Matches": [{"MatchID": "active"}, {"MatchID": f"latest-{puuid}"}, {"MatchID": "older"}]})
            match_id = endpoint.rsplit("/", 1)[-1]
            data = details(match_id)
            data["players"] = [{"subject": puuid, "stats": {"kills": 12, "deaths": 6, "assists": 3}} for puuid in ids]
            data["roundResults"][0]["playerStats"] = [
                {"subject": puuid, "damage": [{"headshots": 2, "bodyshots": 3, "legshots": 0, "damage": 300}]}
                for puuid in ids
            ]
            return response(data)

        self.state.publish("heartbeat", heartbeat)
        worker = RecentStatsSync(SimpleNamespace(headers={}, lockfile={}, fetch=fetch), Mock(), self.state, Mock())
        worker.submit(heartbeat)
        for now in range(20):
            self.assertTrue(worker.process_once(now=now))
        self.assertFalse(worker.process_once(now=21))
        worker.stop()
        for player in self.state.snapshot()["heartbeat"]["players"].values():
            self.assertEqual(player["recentStats"]["matches"], 1)
            self.assertEqual(player["recentStats"]["requestedMatches"], 1)
            self.assertEqual(player["recentStats"]["status"], "ready")
            self.assertEqual(player["kd"], 2)
            self.assertEqual(player["headshotPercentage"], 40)
            self.assertEqual(player["kills"], "N/A")
        self.assertEqual(len(calls), 20)
        detail_calls = [endpoint for endpoint in calls if "/match-details/" in endpoint]
        self.assertEqual(len(detail_calls), 10)
        self.assertTrue(all("/latest-" in endpoint for endpoint in detail_calls))

    def test_stale_account_match_state_or_player_is_ignored(self):
        revision = self.state.get_revision()
        for key, value in (("accountPuuid", "other"), ("matchId", "old"), ("state", "PREGAME"), ("puuid", "missing")):
            self.state.publish("recentStats", self.event | {key: value})
            self.assertEqual(self.state.get_revision(), revision)

    def test_same_context_heartbeat_preserves_recent_stats(self):
        self.state.publish("recentStats", self.event)
        self.state.publish("heartbeat", self.heartbeat)
        self.assertEqual(self.state.snapshot()["heartbeat"]["players"]["a"]["kd"], 1.2)

    def test_new_context_does_not_retain_old_recent_stats(self):
        self.state.publish("recentStats", self.event)
        data = copy.deepcopy(self.heartbeat)
        data["matchId"] = "new"
        self.state.publish("heartbeat", data)
        snapshot = self.state.snapshot()
        self.assertNotIn("recentStats", snapshot["heartbeat"]["players"]["a"])
        self.assertNotIn("recentStats", snapshot["account"]["profile"])
        self.assertEqual(snapshot["account"]["profile"]["kd"], "N/A")

    def test_caption_distinguishes_loading_partial_and_no_history(self):
        for status, expected in (("loading", "загрузка"), ("partial", "часть недоступна"), ("empty", "нет завершённых"), ("unavailable", "API временно")):
            caption = recent_stats_caption({"recentStats": {"status": status, "matches": 2, "availableMatches": 4}})
            self.assertIn("последний завершённый рейтинговый матч", caption)
            self.assertIn(expected, caption)


if __name__ == "__main__":
    unittest.main()
