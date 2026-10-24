import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.recent_stats_sync import RecentStatsSync


def heartbeat(account="self", match="match", state="INGAME", players=("other", "self", "third")):
    return {
        "puuid": account, "matchId": match, "state": state,
        "players": {puuid: {"puuid": puuid} for puuid in players},
    }


def result(status="ready", matches=20):
    return {
        "status": status, "matches": matches, "requestedMatches": 20,
        "availableMatches": 20, "hs": 40, "kd": 2,
        "kills": 20, "deaths": 10, "assists": 5, "adr": 150,
    }


def one_match_result(status="ready"):
    return result(status, 1) | {"requestedMatches": 1, "availableMatches": 1}


class RecentStatsSyncTests(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(headers={"Authorization": "original"}, lockfile={"port": 1})
        self.state = Mock()
        self.log = Mock()
        self.created = []
        self.calls = []
        self.iter_stats = lambda *args, **kwargs: iter([result()])

        def create(client, log, config):
            stats = SimpleNamespace(Requests=client, match_details_cache={})

            def iterate(*args, **kwargs):
                self.calls.append((args, kwargs))
                return self.iter_stats(*args, **kwargs)

            stats.iter_recent_stats = iterate
            self.created.append((stats, threading.current_thread()))
            return stats

        self.factory = patch("src.recent_stats_sync.PlayerStats", side_effect=create)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.worker = RecentStatsSync(self.client, Mock(), self.state, self.log)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        self.worker.stop()
        if self.worker._thread is not None:
            self.worker._thread.join(2)
            self.assertFalse(self.worker._thread.is_alive())

    def events(self):
        return [call.args for call in self.state.publish.call_args_list]

    def test_round_robin_own_first_and_event_contract(self):
        def iterate(puuid, **kwargs):
            yield result("loading", 0)
            yield result("loading", 1)
            yield result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat())
        for now in range(9):
            self.assertTrue(self.worker.process_once(now=now))
        events = self.events()
        self.assertEqual([payload["puuid"] for _, payload in events], ["self", "other", "third"] * 3)
        self.assertEqual([payload["stats"]["matches"] for _, payload in events], [0] * 3 + [1] * 3 + [20] * 3)
        self.assertEqual(events[0], ("recentStats", {
            "accountPuuid": "self", "matchId": "match", "state": "INGAME",
            "puuid": "self", "stats": result("loading", 0),
        }))
        for _, kwargs in self.calls:
            self.assertEqual(kwargs["limit"], 1)
            self.assertEqual(kwargs["exclude_match_id"], "match")
            self.assertFalse(kwargs["should_stop"]())
        self.assertFalse(self.worker.process_once(now=1000))
        self.assertEqual(self.state.publish.call_count, 9)

    def test_repeated_identical_submit_does_not_reset_work(self):
        self.worker.submit(heartbeat())
        for now in range(3):
            self.worker.submit(heartbeat(players=("third", "self", "other")))
            self.assertTrue(self.worker.process_once(now=now))
        for now in range(10, 100):
            data = heartbeat()
            data["time"] = now
            data["players"]["self"]["name"] = str(now)
            self.worker.submit(data)
            self.assertFalse(self.worker.process_once(now=now))
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.created), 1)

    def test_throttle_applies_between_players_and_contexts(self):
        self.worker.submit(heartbeat())
        self.assertTrue(self.worker.process_once(now=0))
        self.assertFalse(self.worker.process_once(now=0.1))
        self.worker.submit(heartbeat(match="next"))
        self.assertFalse(self.worker.process_once(now=0.2))
        self.assertTrue(self.worker.process_once(now=0.35))
        self.assertEqual(self.events()[-1][1]["matchId"], "next")
        self.assertEqual(self.events()[-1][1]["puuid"], "self")

    def test_partial_and_unavailable_retries_are_delayed_and_bounded(self):
        for index, status in enumerate(("partial", "unavailable")):
            with self.subTest(status=status):
                base = index * 2000
                self.iter_stats = lambda *args, **kwargs: iter([result(status, 2 if status == "partial" else 0)])
                self.worker.submit(heartbeat(match=status, players=("self",)))
                self.assertTrue(self.worker.process_once(now=base + 100))
                self.worker.submit(heartbeat(match=status, players=("self",)))
                self.assertFalse(self.worker.process_once(now=base + 129))
                self.assertTrue(self.worker.process_once(now=base + 130))
                self.assertFalse(self.worker.process_once(now=base + 189))
                self.assertTrue(self.worker.process_once(now=base + 190))
                for now in (250, 500, 1000):
                    self.worker.submit(heartbeat(match=status, players=("self",)))
                    self.assertFalse(self.worker.process_once(now=base + now))
        self.assertEqual(len(self.calls), self.worker.MAX_ATTEMPTS * 2)
        self.assertEqual(len(self.created), 2)

    def test_retry_keeps_partial_values_visible_while_reloading(self):
        self.iter_stats = lambda *args, **kwargs: iter([result("partial", 2)])
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=0)
        self.iter_stats = lambda *args, **kwargs: iter([
            result("loading", 0), result("unavailable", 0),
        ])
        self.worker.process_once(now=30)
        loading = self.events()[-1][1]["stats"]
        self.assertEqual(loading["status"], "loading")
        self.assertEqual(loading["matches"], 2)
        self.assertEqual(loading["hs"], 40)
        self.worker.process_once(now=31)
        partial = self.events()[-1][1]["stats"]
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["matches"], 2)

    def test_ready_and_empty_do_not_retry(self):
        self.iter_stats = lambda puuid, **kwargs: iter([result("empty" if puuid == "other" else "ready", 0)])
        self.worker.submit(heartbeat(players=("self", "other")))
        self.assertTrue(self.worker.process_once(now=0))
        self.assertTrue(self.worker.process_once(now=1))
        self.assertFalse(self.worker.process_once(now=10000))
        self.assertEqual(len(self.calls), 2)

    def test_exceptions_become_retryable_without_leaking_details(self):
        def iterate(*args, **kwargs):
            raise RuntimeError("secret response and token")

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self",)))
        for now in (0, 30, 90):
            self.assertTrue(self.worker.process_once(now=now))
        self.assertFalse(self.worker.process_once(now=1000))
        self.assertEqual([event[1]["stats"]["status"] for event in self.events()], ["unavailable"] * 3)
        self.assertNotIn("secret", str(self.log.call_args_list))

    def test_stale_result_during_fetch_is_suppressed_and_submit_does_not_wait(self):
        entered = threading.Event()
        release = threading.Event()
        submitted = threading.Event()
        cancelled = []

        def iterate(puuid, should_stop, **kwargs):
            entered.set()
            release.wait(2)
            cancelled.append(should_stop())
            yield result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self",)))
        fetch_thread = threading.Thread(target=lambda: self.worker.process_once(now=0))
        fetch_thread.start()
        self.addCleanup(fetch_thread.join, 2)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(1))

        def submit():
            self.worker.submit(heartbeat(match="new", players=("self",)))
            submitted.set()

        submit_thread = threading.Thread(target=submit)
        submit_thread.start()
        self.addCleanup(submit_thread.join, 2)
        try:
            self.assertTrue(submitted.wait(0.5), "submit blocked on network work")
        finally:
            release.set()
        fetch_thread.join(1)
        self.assertFalse(fetch_thread.is_alive())
        self.assertEqual(cancelled, [True])
        self.state.publish.assert_not_called()
        self.iter_stats = lambda *args, **kwargs: iter([result()])
        self.assertTrue(self.worker.process_once(now=1))
        self.assertEqual(self.events()[0][1]["matchId"], "new")

    def test_context_identity_includes_account_state_match_and_roster(self):
        contexts = [
            heartbeat(players=("self",)),
            heartbeat(account="next", players=("next",)),
            heartbeat(account="next", state="PREGAME", players=("next",)),
            heartbeat(account="next", state="PREGAME", match="new", players=("next",)),
            heartbeat(account="next", state="PREGAME", match="new", players=("next", "other")),
        ]
        for now, data in enumerate(contexts):
            self.worker.submit(data)
            self.assertTrue(self.worker.process_once(now=now))
        self.assertEqual(len(self.created), 3)
        self.assertEqual([event[1]["accountPuuid"] for event in self.events()], ["self"] + ["next"] * 4)
        self.assertEqual(len(self.worker._jobs), 1)

    def test_context_switch_closes_old_generators_and_discards_cache(self):
        closed = []

        def iterate(*args, **kwargs):
            try:
                self.worker.player_stats.match_details_cache["old"] = {}
                yield result("loading", 1)
                yield result()
            finally:
                closed.append(True)

        self.iter_stats = iterate
        data = heartbeat(players=("self",))
        self.worker.submit(data)
        self.worker.process_once(now=0)
        self.assertIn("old", self.worker.player_stats.match_details_cache)
        data["players"].clear()
        self.worker.submit(data)
        self.assertFalse(self.worker.process_once(now=1))
        self.assertEqual(closed, [True])
        self.assertIsNone(self.worker.player_stats)
        self.assertFalse(self.worker._jobs)

    def test_auth_is_copied_on_worker_thread_and_never_mutates_monitor(self):
        finished = threading.Event()
        observed = []

        def iterate(*args, **kwargs):
            client = self.worker.player_stats.Requests
            observed.append(client)
            client.headers["Authorization"] = "refreshed"
            client.lockfile["port"] = 2
            yield result()

        self.iter_stats = iterate
        self.state.publish.side_effect = lambda *args: finished.set()
        self.worker.submit(heartbeat(players=("self",)))
        self.assertFalse(self.created)
        self.worker.start()
        thread = self.worker._thread
        self.worker.start()
        self.assertIs(thread, self.worker._thread)
        self.assertTrue(finished.wait(1))
        self.worker.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertIs(self.created[0][1], thread)
        self.assertIsNot(observed[0], self.client)
        self.assertIsNot(observed[0].headers, self.client.headers)
        self.assertIsNot(observed[0].lockfile, self.client.lockfile)
        self.assertEqual(self.client.headers, {"Authorization": "original"})
        self.assertEqual(self.client.lockfile, {"port": 1})

    def test_stop_interrupts_backoff_and_idle_wait(self):
        self.iter_stats = lambda *args, **kwargs: iter([result("unavailable", 0)])
        published = threading.Event()
        self.state.publish.side_effect = lambda *args: published.set()
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.start()
        self.assertTrue(published.wait(1))
        self.worker.stop()
        self.worker._thread.join(0.5)
        self.assertFalse(self.worker._thread.is_alive())
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.worker.process_once(now=1000))
        self.worker.submit(heartbeat(match="ignored"))
        self.assertEqual(self.worker._context[1], "match")

        idle = RecentStatsSync(self.client, Mock(), Mock(), Mock())
        idle.start()
        idle.stop()
        idle._thread.join(0.5)
        self.assertFalse(idle._thread.is_alive())

    def test_stop_during_fetch_cancels_callback_and_suppresses_result(self):
        def iterate(puuid, should_stop, **kwargs):
            self.worker.stop()
            self.assertTrue(should_stop())
            yield result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self",)))
        self.assertTrue(self.worker.process_once(now=0))
        self.state.publish.assert_not_called()

    def test_retries_reuse_context_cache_but_get_fresh_isolated_credentials(self):
        clients = []
        caches = []

        def iterate(*args, **kwargs):
            stats = self.worker.player_stats
            clients.append(stats.Requests)
            caches.append(stats.match_details_cache)
            stats.match_details_cache["cached"] = {}
            yield result("partial", 1)

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=0)
        self.client.headers["Authorization"] = "new monitor token"
        self.worker.process_once(now=30)
        self.assertEqual(len(self.created), 1)
        self.assertIs(caches[0], caches[1])
        self.assertIsNot(clients[0], clients[1])
        self.assertEqual(clients[1].headers["Authorization"], "new monitor token")
        self.assertIsNot(clients[1].headers, self.client.headers)

    def test_same_match_pregame_to_ingame_republishes_ready_in_current_context(self):
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        self.worker.submit(heartbeat(state="PREGAME", players=("self", "other")))
        self.worker.process_once(now=0)
        self.worker.process_once(now=1)
        stats = self.worker.player_stats
        stats.match_details_cache["previous"] = {"players": []}
        self.worker.submit(heartbeat(players=("self", "other")))
        self.worker.process_once(now=2)
        self.worker.process_once(now=3)
        self.assertEqual(len(self.calls), 2)
        self.assertIs(self.worker.player_stats, stats)
        self.assertIn("previous", stats.match_details_cache)
        self.assertEqual([payload["state"] for _, payload in self.events()],
                         ["PREGAME", "PREGAME", "INGAME", "INGAME"])
        self.assertTrue(all(payload["stats"] == one_match_result() for _, payload in self.events()))

    def test_match_details_are_reused_for_new_player_across_active_transition(self):
        from src.player_stats import PlayerStats

        self.factory.stop()
        self.factory = patch("src.recent_stats_sync.PlayerStats", wraps=PlayerStats)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        calls = []

        def fetch(service, path, method):
            calls.append(path)
            if "competitiveupdates" in path:
                return Mock(status_code=200, json=lambda: {"Matches": [{"MatchID": "previous"}]})
            return Mock(status_code=200, json=lambda: {
                "gameInfo": {"matchId": "previous", "isCompleted": True},
                "players": [
                    {"subject": puuid, "stats": {"kills": 12, "deaths": 6, "assists": 3}}
                    for puuid in ("self", "other")
                ],
            })

        self.client.fetch = fetch
        self.worker.submit(heartbeat(state="PREGAME", players=("self",)))
        self.worker.process_once(now=0)
        self.worker.process_once(now=1)
        self.worker.submit(heartbeat(players=("self", "other")))
        for now in range(2, 5):
            self.worker.process_once(now=now)
        self.assertEqual(sum("competitiveupdates" in path for path in calls), 2)
        self.assertEqual(sum("match-details" in path for path in calls), 1)
        self.assertEqual(self.events()[-1][1]["stats"]["status"], "ready")
        self.assertEqual(self.events()[-1][1]["puuid"], "other")

    def test_roster_addition_fetches_only_new_player(self):
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        self.worker.submit(heartbeat(state="PREGAME", players=("self",)))
        self.worker.process_once(now=0)
        self.worker.submit(heartbeat(players=("self", "other")))
        self.worker.process_once(now=1)
        self.worker.process_once(now=2)
        self.assertEqual([args[0] for args, _ in self.calls], ["self", "other"])
        self.assertEqual([payload["puuid"] for _, payload in self.events()], ["self", "self", "other"])

    def test_menu_transition_invalidates_even_when_worker_skips_menu_context(self):
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=0)
        old_stats = self.worker.player_stats
        old_stats.match_details_cache["previous"] = {}
        self.worker.submit(heartbeat(state="MENUS", match=None, players=()))
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=1)
        self.assertEqual(len(self.calls), 2)
        self.assertIsNot(self.worker.player_stats, old_stats)
        self.assertFalse(self.worker.player_stats.match_details_cache)

    def test_account_disconnect_and_different_match_invalidate_reuse(self):
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        contexts = [
            heartbeat(players=("other",)),
            heartbeat(account="next", players=("other",)),
            heartbeat(account="next", match="new", players=("other",)),
            heartbeat(account=None, state="DISCONNECTED", players=()),
            heartbeat(account="next", match="new", players=("other",)),
        ]
        for now, context in enumerate(contexts):
            self.worker.submit(context)
            self.worker.process_once(now=now)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(self.created), 4)

    def test_ready_cache_expires_and_is_bounded_without_caching_failures(self):
        self.worker.CACHE_MAX_SIZE = 2
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        self.worker.submit(heartbeat())
        for now in range(3):
            self.worker.process_once(now=now)
        self.assertEqual(len(self.worker._ready_cache), 2)
        self.worker.player_stats.match_details_cache.update({str(i): {} for i in range(4)})
        self.worker._prune_cache(3)
        self.assertEqual(len(self.worker.player_stats.match_details_cache), 2)
        self.worker.submit(heartbeat(state="PREGAME"))
        for now in range(303, 306):
            self.worker.process_once(now=now)
        self.assertEqual(len(self.calls), 6)
        self.assertFalse(self.worker.player_stats.match_details_cache)
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result("unavailable")])
        self.worker.submit(heartbeat(match="failure", players=("self",)))
        self.worker.process_once(now=400)
        self.worker.submit(heartbeat(match="failure", state="PREGAME", players=("self",)))
        self.worker.process_once(now=401)
        self.assertEqual(len(self.calls), 8)
        self.assertFalse(self.worker._ready_cache)

    def test_worker_refreshed_auth_persists_across_players_and_contexts(self):
        observed = []

        def iterate(*args, **kwargs):
            client = self.worker.player_stats.Requests
            observed.append((client, dict(client.headers), dict(client.lockfile)))
            client.headers["Authorization"] = "worker refreshed"
            client.lockfile["port"] = 2
            yield one_match_result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self", "other")))
        self.worker.process_once(now=0)
        self.worker.process_once(now=1)
        self.assertIs(observed[0][0], observed[1][0])
        self.assertEqual(observed[1][1]["Authorization"], "worker refreshed")
        self.assertEqual(observed[1][2]["port"], 2)
        self.worker.submit(heartbeat(match="next", players=("self",)))
        self.worker.process_once(now=2)
        self.assertIs(observed[1][0], observed[2][0])
        self.client.headers["Authorization"] = "source changed"
        self.worker.submit(heartbeat(match="third", players=("self",)))
        self.worker.process_once(now=3)
        self.assertIsNot(observed[2][0], observed[3][0])
        self.assertEqual(observed[3][1]["Authorization"], "source changed")
        self.assertEqual(observed[3][2]["port"], 1)
        self.assertEqual(self.client.headers["Authorization"], "source changed")
        self.assertEqual(self.client.lockfile["port"], 1)

    def test_skipped_disconnect_discards_worker_auth_and_cache(self):
        observed = []

        def iterate(*args, **kwargs):
            client = self.worker.player_stats.Requests
            observed.append(dict(client.headers))
            client.headers["Authorization"] = "worker refreshed"
            yield one_match_result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=0)
        self.worker.submit(heartbeat(account=None, state="DISCONNECTED", players=()))
        self.worker.submit(heartbeat(players=("self",)))
        self.worker.process_once(now=1)
        self.assertEqual(observed, [{"Authorization": "original"}] * 2)
        self.assertEqual(len(self.calls), 2)

    def test_cancelled_same_match_fetch_is_not_saved_as_ready(self):
        def iterate(*args, **kwargs):
            self.worker.submit(heartbeat(players=("self",)))
            yield one_match_result()

        self.iter_stats = iterate
        self.worker.submit(heartbeat(state="PREGAME", players=("self",)))
        self.worker.process_once(now=0)
        self.state.publish.assert_not_called()
        self.assertFalse(self.worker._ready_cache)
        self.iter_stats = lambda *args, **kwargs: iter([one_match_result()])
        self.worker.process_once(now=1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.events()[0][1]["state"], "INGAME")


if __name__ == "__main__":
    unittest.main()
