import ast
from pathlib import Path
import time
import threading
import unittest
from unittest.mock import Mock

from src.player_stats import PlayerStats


SOURCE = Path(__file__).resolve().parents[1] / "main.py"


def monitor_functions(*names, **namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class MonitorWiringTests(unittest.TestCase):
    def setUp(self):
        self.rank = Mock()
        self.rank.get_rank.return_value = {"rank": 15, "rr": 30, "statusgood": True}
        self.pstats = PlayerStats(Mock(), Mock(), Mock())
        self.cache = {"match_id": None, "players": {}}
        self.namespace = monitor_functions(
            "reset_match_player_cache", "ensure_match_player_cache", "get_or_fetch_rank_and_stats",
            rank=self.rank, pstats=self.pstats, match_player_cache=self.cache,
            seasonID="current", previousSeasonID="previous", time=time,
            MATCH_PLAYER_CACHE_TTL_SECONDS=300,
        )

    def test_active_match_does_not_request_past_details_on_monitor_thread(self):
        fetch = self.namespace["get_or_fetch_rank_and_stats"]
        result = fetch("player", "active")
        self.assertEqual(result[2]["kd"], "N/A")
        self.pstats.Requests.fetch.assert_not_called()
        self.assertEqual(fetch("player", "active"), result)
        self.assertEqual(self.rank.get_rank.call_count, 2)

    def test_failed_rank_is_not_pinned_for_entire_match(self):
        self.rank.get_rank.return_value = {"rank": 0, "statusgood": False}
        fetch = self.namespace["get_or_fetch_rank_and_stats"]
        fetch("player", "active")
        self.assertEqual(self.cache["players"], {})
        self.rank.get_rank.return_value = {"rank": 15, "statusgood": True}
        self.assertEqual(fetch("player", "active")[0]["rank"], 15)

    def test_new_match_resets_player_cache(self):
        fetch = self.namespace["get_or_fetch_rank_and_stats"]
        fetch("player", "old")
        fetch("player", "new")
        self.assertEqual(self.rank.get_rank.call_count, 4)
        self.assertEqual(self.cache["match_id"], "new")

    def test_shutdown_stops_workers_and_preserves_pending_history(self):
        store, history, recent, state, rpc = (Mock() for _ in range(5))
        pending = {"player": {"match_id": "active", "kills": "N/A"}}
        namespace = monitor_functions(
            "flush_match_data", "shutdown_monitor", stats=store, history_sync=history,
            recent_stats_sync=recent, app_state=state, pending_match_data=pending,
            pending_match_lock=threading.RLock(), rpc=rpc, log=Mock(),
        )
        namespace["shutdown_monitor"]()
        store.save_data.assert_called_once_with({"player": {"match_id": "active", "kills": "N/A"}})
        self.assertEqual(pending, {})
        history.stop.assert_called_once()
        recent.stop.assert_called_once()
        rpc.shutdown.assert_called_once()
        namespace["shutdown_monitor"]()
        store.save_data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
