import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.app_state import AppStateStore
from src.history_sync import HistorySync
from src.party import history_party_labels, normalize_party_id
from src.player_stats import PlayerStats
from src.stats import Stats


def match_data(match_id="match"):
    return {
        "matchInfo": {"matchId": match_id, "isCompleted": True},
        "players": [
            {"subject": subject, "partyId": party, "stats": {"kills": 10, "deaths": 5, "assists": 2}}
            for subject, party in (("self", "own"), ("friend", "own"), ("enemy1", "enemy"), ("enemy2", "enemy"), ("solo", "alone"))
        ],
    }


def response(data):
    result = Mock(status_code=200)
    result.json.return_value = data
    return result


def totals():
    return {"hs": 20, "kd": 2, "kills": 10, "deaths": 5, "assists": 2, "adr": 120}


class PartyExtractionTests(unittest.TestCase):
    def test_ids_are_from_exact_completed_match_and_cache_is_shared(self):
        client = Mock()
        client.fetch.return_value = response(match_data())
        stats = PlayerStats(client, Mock(), Mock())
        status, players = stats.get_match_stats("match")
        self.assertEqual(status, "ready")
        self.assertEqual(players["enemy1"]["partyId"], "enemy")
        self.assertTrue(players["enemy1"]["partyResolved"])
        self.assertEqual(players["self"]["kd"], 2)
        stats.get_match_stats("match")
        client.fetch.assert_called_once_with("pd", "/match-details/v1/matches/match", "get")

    def test_absent_or_invalid_party_is_checked_but_not_invented(self):
        for party in (None, "", " ", "00000000-0000-0000-0000-000000000000", [], {}, True, 1, "x" * 129):
            with self.subTest(party=party):
                data = match_data()
                data["players"][0]["partyId"] = party
                client = Mock()
                client.fetch.return_value = response(data)
                _, players = PlayerStats(client, Mock(), Mock()).get_match_stats("match")
                self.assertIsNone(players["self"]["partyId"])
                self.assertTrue(players["self"]["partyResolved"])
        self.assertEqual(normalize_party_id(" party "), "party")

    def test_pending_or_wrong_match_cannot_confirm_parties(self):
        for change in ({"isCompleted": False}, {"matchId": "different"}):
            data = match_data()
            data["matchInfo"].update(change)
            client = Mock()
            client.fetch.return_value = response(data)
            self.assertEqual(PlayerStats(client, Mock(), Mock()).get_match_stats("match"), ("pending", {}))

    def test_only_confirmed_groups_with_multiple_members_get_labels(self):
        players = {
            "a": {"partyId": "p", "partyResolved": True},
            "b": {"partyId": "p", "partyResolved": True},
            "c": {"partyId": "p", "partyResolved": False},
            "d": {"partyId": None, "partyResolved": True},
            "e": {"partyId": "solo", "partyResolved": True},
        }
        self.assertEqual(history_party_labels(players), {
            "a": {"partyNumber": 1, "partySize": 2},
            "b": {"partyNumber": 1, "partySize": 2},
        })


class HistoryPartyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict(os.environ, {"APPDATA": temporary.name})
        env.start()
        self.addCleanup(env.stop)
        self.stats = Stats()
        self.state = AppStateStore()
        self.client = SimpleNamespace(headers={}, lockfile={}, fetch=Mock(return_value=response(match_data())))
        self.worker = HistorySync(self.stats, self.client, Mock(), self.state, Mock())
        self.addCleanup(self.worker.stop)

    def save(self, match_id="match", epoch=100, resolved=True):
        self.stats.save_data({
            player["subject"]: totals() | {"match_id": match_id, "epoch": epoch, "name": player["subject"],
                                          "statsResolved": resolved, "team": "Red" if "enemy" in player["subject"] else "Blue"}
            for player in match_data()["players"]
        })

    def test_old_complete_stats_are_upgraded_without_duplicates_or_metadata_loss(self):
        self.save()
        self.assertIn("match", self.stats.get_incomplete_matches())
        self.assertTrue(self.worker.process_once(now=0))
        records = self.stats.read_data()
        for subject in records:
            self.assertEqual(len(records[subject]), 1)
            self.assertEqual(records[subject][0]["epoch"], 100)
            self.assertEqual(records[subject][0]["name"], subject)
            self.assertTrue(records[subject][0]["partyResolved"])
            self.assertEqual(records[subject][0]["hs"], 20)
        history = self.stats.get_history()[0]["players"]
        self.assertEqual(history["self"]["partyNumber"], history["friend"]["partyNumber"])
        self.assertEqual(history["enemy1"]["partyNumber"], history["enemy2"]["partyNumber"])
        self.assertNotEqual(history["self"]["partyNumber"], history["enemy1"]["partyNumber"])
        self.assertEqual(history["enemy1"]["partySize"], 2)
        self.assertEqual(history["solo"]["partyNumber"], 0)
        self.assertEqual(history["enemy1"]["partySource"], "match-results")
        self.assertFalse(self.worker.process_once(now=1000))
        self.client.fetch.assert_called_once()
        self.assertEqual(self.state.snapshot()["history_revision"], 1)

    def test_missing_party_field_finishes_without_endless_retries_or_solo_claim(self):
        self.save()
        data = match_data()
        for player in data["players"]:
            player.pop("partyId")
        self.client.fetch.return_value = response(data)
        self.worker.process_once(now=0)
        self.assertFalse(self.stats.get_incomplete_matches())
        self.assertFalse(self.worker.process_once(now=1000))
        player = self.stats.get_history()[0]["players"]["enemy1"]
        self.assertIsNone(player["partyId"])
        self.assertEqual(player["partyNumber"], 0)
        self.assertTrue(player["partyResolved"])
        self.client.fetch.assert_called_once()

    def test_unchecked_legacy_live_labels_are_not_shown_in_history(self):
        self.stats.save_data({p: {"match_id": "match", "partyNumber": 1, "partyId": "old-live"} for p in ("a", "b")})
        for player in self.stats.get_history()[0]["players"].values():
            self.assertEqual(player["partyNumber"], 0)
            self.assertFalse(player["partyResolved"])

    def test_partial_metadata_does_not_erase_known_party_or_set_checked(self):
        self.save()
        self.worker.process_once(now=0)
        self.stats.update_match_stats("match", {"enemy1": {"hs": 25, "partyId": None}})
        entry = self.stats.read_data()["enemy1"][0]
        self.assertEqual(entry["partyId"], "enemy")
        self.assertTrue(entry["partyResolved"])
        self.assertEqual(entry["hs"], 25)
        self.stats.update_match_stats("match", {"enemy1": {"partyId": None, "partyResolved": True}})
        self.assertEqual(self.stats.read_data()["enemy1"][0]["partyId"], "enemy")

    def test_labels_do_not_cross_match_boundaries(self):
        for match_id in ("one", "two"):
            self.stats.save_data({match_id: {"match_id": match_id, "partyId": "shared", "partyResolved": True}})
        for match in self.stats.get_history():
            self.assertTrue(all(player["partyNumber"] == 0 for player in match["players"].values()))

    def test_party_only_backfill_is_limited_to_recent_window(self):
        for index in range(35):
            self.stats.save_data({"a": totals() | {"match_id": f"m{index}", "epoch": index, "statsResolved": True}})
        for index in range(5, 35):
            self.stats.update_match_stats(f"m{index}", {"a": {"partyResolved": True, "partyId": None}})
        self.assertFalse(self.stats.get_incomplete_matches(30))
        self.assertFalse(self.worker.process_once(now=0))
        self.client.fetch.assert_not_called()

    def test_active_match_excluded_and_live_party_values_not_changed(self):
        self.save()
        heartbeat = {"state": "INGAME", "matchId": "match", "puuid": "self", "players": {"self": {"partyNumber": 8}}}
        self.state.publish("heartbeat", heartbeat)
        self.worker.set_active_match("match")
        self.assertFalse(self.worker.process_once(now=0))
        self.client.fetch.assert_not_called()
        self.worker.set_active_match(None)
        self.worker.process_once(now=1)
        self.assertEqual(self.state.snapshot()["heartbeat"], heartbeat)

    def test_clear_during_party_backfill_does_not_restore_history(self):
        self.save()
        def fetch(*args):
            self.stats.clear_data()
            return response(match_data())
        self.client.fetch.side_effect = fetch
        self.worker.process_once(now=0)
        self.assertEqual(self.stats.read_data(), {})


if __name__ == "__main__":
    unittest.main()
