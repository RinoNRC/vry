import copy
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.history_sync import HistorySync
from src.stats import Stats


def player_stats():
    return {"hs": 40, "kd": 2, "kills": 12, "deaths": 6, "assists": 3, "adr": 150,
            "partyId": None, "partyResolved": True}


class HistorySyncReliabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"APPDATA": temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.stats = Stats()
        self.stats.save_data({
            puuid: {"match_id": "match", "epoch": 100, "hs": "N/A", "kd": "N/A"}
            for puuid in ("self", "other")
        })
        self.client = SimpleNamespace(headers={"Authorization": "source"}, lockfile={"port": 1})
        self.state = Mock()
        self.log = Mock()
        self.factory = patch("src.history_sync.PlayerStats")
        factory = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.player_stats = factory.return_value
        self.player_stats.get_match_stats.return_value = ("pending", {})
        self.worker = HistorySync(self.stats, self.client, Mock(), self.state, self.log)
        self.addCleanup(self.worker.stop)

    def test_worker_auth_refresh_persists_until_source_changes(self):
        observed = []

        def fetch(match_id):
            client = self.player_stats.Requests
            observed.append((client, dict(client.headers), dict(client.lockfile)))
            client.headers["Authorization"] = "worker refreshed"
            client.lockfile["port"] = 2
            return "pending", {}

        self.player_stats.get_match_stats.side_effect = fetch
        for now in (0, 15):
            self.assertTrue(self.worker.process_once(now=now))
        self.assertIs(observed[0][0], observed[1][0])
        self.assertEqual(observed[1][1], {"Authorization": "worker refreshed"})
        self.assertEqual(observed[1][2], {"port": 2})
        self.client.headers["Authorization"] = "source changed"
        self.worker.process_once(now=45)
        self.assertIsNot(observed[1][0], observed[2][0])
        self.assertEqual(observed[2][1], {"Authorization": "source changed"})
        self.assertEqual(observed[2][2], {"port": 1})
        self.client.lockfile["port"] = 3
        self.worker.process_once(now=105)
        self.assertIsNot(observed[2][0], observed[3][0])
        self.assertEqual(observed[3][2], {"port": 3})
        self.assertEqual(self.client.headers, {"Authorization": "source changed"})
        self.assertEqual(self.client.lockfile, {"port": 3})

    def test_auth_copy_happens_on_worker_thread(self):
        copied = []
        finished = threading.Event()
        original_copy = copy.copy

        def copy_client(client):
            copied.append(threading.current_thread())
            return original_copy(client)

        self.player_stats.get_match_stats.side_effect = lambda match_id: (finished.set() or "pending", {})
        with patch("src.history_sync.copy.copy", side_effect=copy_client):
            thread = threading.Thread(target=lambda: self.worker.process_once(now=0))
            thread.start()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(copied, [thread])
        self.assertIsNot(self.player_stats.Requests.headers, self.client.headers)
        self.assertIsNot(self.player_stats.Requests.lockfile, self.client.lockfile)

    def test_clear_during_fetch_does_not_write_or_publish_or_invalidate_other_cache(self):
        def fetch(match_id):
            self.stats.clear_data()
            return "ready", {"self": player_stats()}

        self.player_stats.get_match_stats.side_effect = fetch
        with patch.object(self.stats, "update_match_stats", wraps=self.stats.update_match_stats) as update:
            self.assertTrue(self.worker.process_once(now=0))
        update.assert_not_called()
        self.assertEqual(self.stats.read_data(), {})
        self.state.publish.assert_not_called()
        self.player_stats.invalidate_match.assert_not_called()
        self.player_stats.clear_runtime_cache.assert_not_called()
        self.assertFalse(self.worker._jobs)

    def test_already_resolved_during_fetch_is_not_invalidated(self):
        def fetch(match_id):
            self.stats.update_match_stats(match_id, {p: player_stats() for p in ("self", "other")})
            return "ready", {"self": player_stats()}

        self.player_stats.get_match_stats.side_effect = fetch
        self.worker.process_once(now=0)
        self.assertFalse(self.stats.get_incomplete_matches())
        self.player_stats.invalidate_match.assert_not_called()
        self.state.publish.assert_not_called()
        self.assertFalse(self.worker._jobs)

    def test_partial_result_invalidates_only_that_match_and_retries(self):
        self.player_stats.get_match_stats.side_effect = [
            ("ready", {"self": player_stats()}),
            ("ready", {"self": player_stats(), "other": player_stats()}),
        ]
        self.worker.process_once(now=0)
        self.player_stats.invalidate_match.assert_called_once_with("match")
        self.assertEqual(self.stats.get_incomplete_matches()["match"]["players"], {"other"})
        self.assertFalse(self.worker.process_once(now=14))
        self.assertTrue(self.worker.process_once(now=15))
        self.assertFalse(self.stats.get_incomplete_matches())
        self.assertEqual(self.state.publish.call_count, 2)
        self.player_stats.clear_runtime_cache.assert_not_called()

    def test_ready_without_complete_core_values_is_not_cached_forever(self):
        self.player_stats.get_match_stats.return_value = ("ready", {
            "self": {"hs": 40}, "other": {"hs": 20},
        })
        self.worker.process_once(now=0)
        self.player_stats.invalidate_match.assert_called_once_with("match")
        self.assertTrue(self.worker.process_once(now=15))
        self.assertEqual(self.player_stats.get_match_stats.call_count, 2)

    def test_stop_during_fetch_suppresses_history_write(self):
        def fetch(match_id):
            self.worker.stop()
            return "ready", {p: player_stats() for p in ("self", "other")}

        self.player_stats.get_match_stats.side_effect = fetch
        self.worker.process_once(now=0)
        self.assertTrue(self.stats.get_incomplete_matches())
        self.state.publish.assert_not_called()
        self.assertFalse(self.worker.process_once(now=1000))
        self.worker.start()
        self.assertIsNone(self.worker._thread)

    def test_match_becoming_active_during_fetch_is_not_written(self):
        def fetch(match_id):
            self.worker.set_active_match(match_id)
            return "ready", {p: player_stats() for p in ("self", "other")}

        self.player_stats.get_match_stats.side_effect = fetch
        self.worker.process_once(now=0)
        self.assertTrue(self.stats.get_incomplete_matches())
        self.state.publish.assert_not_called()
        self.assertFalse(self.worker.process_once(now=15))


if __name__ == "__main__":
    unittest.main()
