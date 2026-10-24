import json
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.app_state import AppStateStore
from src.history_sync import HistorySync
from src.player_stats import PlayerStats
from src.stat_format import format_stat
from src.stats import Stats


def match_data():
    return {
        "gameInfo": {"matchId": "match", "isCompleted": True},
        "players": [
            {"subject": "a", "stats": {"kills": 12, "deaths": 6, "assists": 3}},
            {"subject": "b", "stats": {"kills": 0, "deaths": 0, "assists": 0}},
        ],
        "roundResults": [
            {"playerStats": [
                {"subject": "a", "damage": [{"headshots": 2, "bodyshots": 3, "legshots": 0, "damage": 300}]},
                {"subject": "b", "damage": []},
            ]},
            {"playerStats": [
                {"subject": "a", "damage": []},
                {"subject": "b", "damage": []},
            ]},
        ],
    }


def response(status=200, payload=None):
    result = Mock(status_code=status)
    result.json.return_value = match_data() if payload is None else payload
    return result


class PlayerStatsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.fetch.return_value = response()
        self.config = Mock()
        self.config.get_table_flag.return_value = False
        self.stats = PlayerStats(self.client, Mock(), self.config)

    def test_calculation_and_cache_for_all_players(self):
        status, players = self.stats.get_match_stats("match")
        self.assertEqual(status, "ready")
        self.assertEqual(players["a"]["kd"], 2)
        self.assertEqual(players["a"]["hs"], 40)
        self.assertEqual(players["a"]["adr"], 150)
        self.assertEqual(players["a"]["assists"], 3)
        self.assertEqual(players["b"]["kd"], 0)
        self.assertEqual(players["b"]["hs"], "N/A")
        self.stats.get_stats("b", "match")
        self.assertEqual(self.client.fetch.call_count, 1)

    def test_404_then_200_and_negative_cache(self):
        self.client.fetch.side_effect = [response(404), response()]
        with patch("src.player_stats.time.monotonic", return_value=0):
            self.assertEqual(self.stats.get_match_stats("match"), ("pending", {}))
            self.stats.get_stats("a", "match")
            self.stats.get_stats("b", "match")
        self.assertEqual(self.client.fetch.call_count, 1)
        with patch("src.player_stats.time.monotonic", return_value=16):
            self.assertEqual(self.stats.get_stats("a", "match")["hs"], 40)
        self.assertEqual(self.client.fetch.call_count, 2)

    def test_failures_are_not_final_cache_entries(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.stats.clear_runtime_cache()
                self.client.fetch.return_value = response(status)
                self.assertEqual(self.stats.get_match_stats("match"), ("pending", {}))
                self.assertNotIn("match", self.stats.match_details_cache)

    def test_json_and_connection_errors(self):
        self.client.fetch.return_value.json.side_effect = ValueError("bad json")
        self.assertEqual(self.stats.get_match_stats("match"), ("unavailable", {}))
        self.stats.clear_runtime_cache()
        self.client.fetch.side_effect = TimeoutError()
        self.assertEqual(self.stats.get_match_stats("match"), ("unavailable", {}))

    def test_incomplete_and_wrong_match_payloads(self):
        payloads = [{}, {"players": []}, {"players": [{"subject": "a", "stats": None}]}]
        data = match_data()
        data["gameInfo"]["isCompleted"] = False
        payloads.append(data)
        data = match_data()
        data["gameInfo"]["matchId"] = "other"
        payloads.append(data)
        for payload in payloads:
            with self.subTest(payload=payload):
                self.stats.clear_runtime_cache()
                self.client.fetch.return_value = response(payload=payload)
                self.assertEqual(self.stats.get_match_stats("match"), ("pending", {}))
                self.assertFalse(self.stats.match_details_cache)

    def test_missing_player_never_produces_zero_totals(self):
        self.assertEqual(self.stats.get_stats("missing", "match")["kills"], "N/A")
        data = match_data()
        data["players"][0]["stats"] = None
        self.assertEqual(self.stats._process_match_data("a", data, {})["kd"], "N/A")

    def test_absent_rounds_and_zero_deaths(self):
        data = match_data()
        data["players"][0]["stats"]["deaths"] = 0
        data.pop("roundResults")
        result = self.stats._process_match_data("a", data, {})
        self.assertEqual(result["kd"], 12)
        self.assertEqual(result["hs"], "N/A")
        self.assertEqual(result["adr"], "N/A")

    def test_hidden_columns_do_not_disable_collection(self):
        result = self.stats.get_stats("a", "match")
        self.assertEqual(result["kills"], 12)
        self.config.get_table_flag.assert_not_called()

    def test_previous_match_only_when_no_target_is_requested(self):
        self.client.fetch.side_effect = [
            response(payload={"Matches": [{"MatchID": "match", "RankedRatingEarned": 18, "AFKPenalty": 0}]}),
            response(),
        ]
        result = self.stats.get_stats("a")
        self.assertEqual(result["RankedRatingEarned"], 18)
        self.assertEqual(result["hs"], 40)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name})
        self.env.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.env.stop)
        self.stats = Stats()
        self.stats.save_data({p: {"match_id": "match", "epoch": 100, "name": p, "hs": "N/A", "kd": "N/A"} for p in ("a", "b")})

    def worker(self):
        client = Mock(headers={"Authorization": "private"}, lockfile={"port": 1})
        client.fetch.return_value = response()
        self.state = AppStateStore()
        return HistorySync(self.stats, client, Mock(), self.state, Mock())

    def test_retry_repairs_same_records_and_signals_ui(self):
        worker = self.worker()
        worker.client.fetch.side_effect = [response(404), response()]
        with patch("src.player_stats.time.monotonic", return_value=0):
            worker.process_once(now=0)
        self.assertEqual(self.stats.read_data()["a"][0]["hs"], "N/A")
        with patch("src.player_stats.time.monotonic", return_value=16):
            worker.process_once(now=16)
        records = self.stats.read_data()
        self.assertEqual(records["a"][0]["hs"], 40)
        self.assertEqual(records["a"][0]["adr"], 150)
        self.assertEqual(records["a"][0]["epoch"], 100)
        self.assertEqual(len(records["a"]), 1)
        self.assertEqual(worker.client.fetch.call_count, 2)
        self.assertEqual(self.state.snapshot()["history_revision"], 1)
        self.assertFalse(self.stats.get_incomplete_matches())
        self.assertFalse(worker.process_once(now=1000))
        self.assertEqual(worker.client.headers, {"Authorization": "private"})
        self.assertIsNot(worker.player_stats.Requests.headers, worker.client.headers)

    def test_partial_player_list_is_retried_not_cached_forever(self):
        worker = self.worker()
        partial = match_data()
        partial["players"] = partial["players"][:1]
        worker.client.fetch.side_effect = [response(payload=partial), response()]
        worker.process_once(now=0)
        self.assertFalse(self.stats.read_data()["b"][0].get("statsResolved"))
        worker.process_once(now=16)
        self.assertTrue(self.stats.read_data()["b"][0]["statsResolved"])
        self.assertEqual(worker.client.fetch.call_count, 2)

    def test_active_match_is_excluded(self):
        worker = self.worker()
        worker.set_active_match("match")
        self.assertFalse(worker.process_once(now=0))
        worker.client.fetch.assert_not_called()
        worker.set_active_match(None)
        self.assertTrue(worker.process_once(now=1))

    def test_backoff_and_attempt_limit(self):
        worker = self.worker()
        worker.player_stats.get_match_stats = Mock(return_value=("pending", {}))
        worker.process_once(now=0)
        self.assertFalse(worker.process_once(now=1))
        for attempt in range(1, worker.MAX_ATTEMPTS):
            self.assertTrue(worker.process_once(now=attempt * 1000))
        self.assertFalse(worker.process_once(now=100000))
        self.assertEqual(worker.player_stats.get_match_stats.call_count, worker.MAX_ATTEMPTS)
        self.assertIn("match", self.stats.get_incomplete_matches())
        restarted = self.worker()
        self.assertTrue(restarted.process_once(now=0))

    def test_updates_preserve_known_numbers_and_metadata(self):
        self.stats.update_match_stats("match", {"a": {"hs": 40, "kd": 2}})
        self.stats.update_match_stats("match", {"a": {"hs": "N/A", "kd": None}})
        entry = self.stats.read_data()["a"][0]
        self.assertEqual(entry["hs"], 40)
        self.assertEqual(entry["kd"], 2)
        self.assertEqual(entry["name"], "a")
        self.stats.save_data({"a": {"match_id": "match", "epoch": 999}})
        self.assertEqual(len(self.stats.read_data()["a"]), 1)
        self.assertEqual(self.stats.read_data()["a"][0]["epoch"], 100)

    def test_backup_and_corrupt_history_are_preserved(self):
        self.stats.update_match_stats("match", {"a": {"hs": 20}})
        with open(self.stats.path + ".bak", encoding="utf-8") as file:
            self.assertEqual(json.load(file)["a"][0]["hs"], "N/A")
        with open(self.stats.path, "w", encoding="utf-8") as file:
            file.write("broken")
        with self.assertRaises(ValueError):
            self.stats.update_match_stats("match", {"a": {"hs": 90}})
        with self.assertRaises(ValueError):
            self.stats.save_data({"a": {"match_id": "new"}})
        with open(self.stats.path, encoding="utf-8") as file:
            self.assertEqual(file.read(), "broken")

    def test_concurrent_saves_and_updates(self):
        errors = []
        def save(index):
            try:
                Stats().save_data({"a": {"match_id": f"m{index}", "epoch": index}})
                Stats().update_match_stats("match", {"a": {"hs": 40}})
                self.assertIsInstance(Stats().read_data(), dict)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=save, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(errors)
        self.assertEqual(len(self.stats.read_data()["a"]), 13)
        self.assertEqual(self.stats.read_data()["a"][0]["hs"], 40)

    def test_clear_during_request_does_not_resurrect_history(self):
        worker = self.worker()
        def fetch(*args):
            self.stats.clear_data()
            return response()
        worker.client.fetch.side_effect = fetch
        worker.process_once(now=0)
        self.assertEqual(self.stats.read_data(), {})

    def test_stop_interrupts_wait(self):
        worker = self.worker()
        worker.start()
        worker.stop()
        worker._thread.join(timeout=1)
        self.assertFalse(worker._thread.is_alive())


class FormattingTests(unittest.TestCase):
    def test_missing_values_never_have_percent_suffix(self):
        for value in (None, "N/A", "-", "", float("nan"), True):
            self.assertEqual(format_stat(value, "%"), "—")
        self.assertEqual(format_stat(0, "%"), "0%")
        self.assertEqual(format_stat(40, "%"), "40%")
        self.assertEqual(format_stat(1.25), "1.25")


if __name__ == "__main__":
    unittest.main()
