import base64
import json
import unittest
from unittest.mock import Mock

from src.presences import Presences


def encoded(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


class PresencesTests(unittest.TestCase):
    def setUp(self):
        self.requests = Mock(puuid="self")
        self.presences = Presences(self.requests, Mock())

    def test_malformed_private_is_harmless(self):
        for private in (None, "", "!!!", "a", "é", "not-json", "e30", [], 5,
                        encoded([]), encoded(None), encoded(True), encoded("text"),
                        base64.b64encode(b"\xff").decode(), "{bad", b"\xff"):
            with self.subTest(private=private):
                self.assertIsNone(self.presences.decode_private(private))
                self.assertFalse(self.presences.decode_presence(private)["isValid"])

    def test_encoded_raw_and_dictionary_private(self):
        data = {"isValid": True, "sessionLoopState": "MENUS"}
        for private in (encoded(data), encoded(data).encode(), json.dumps(data), data):
            with self.subTest(private=private):
                self.assertEqual(self.presences.decode_private(private), data)
                self.assertEqual(self.presences.decode_presence(private), data)
        self.assertFalse(self.presences.decode_presence({"isValid": "yes"})["isValid"])

    def test_missing_and_malformed_presence_collections(self):
        for entries in (None, [], {}, "bad", [None, {}, [], {"puuid": "other"}]):
            self.assertIsNone(self.presences.get_private_presence(entries))
            self.assertIsNone(self.presences.get_game_state(entries))
        for response in (None, {}, [], {"presences": None}, {"presences": {}}):
            self.requests.fetch.return_value = response
            self.assertIsNone(self.presences.get_presence())
        self.requests.fetch.return_value = {"presences": []}
        self.assertEqual(self.presences.get_presence(), [])

    def test_flat_nested_and_unknown_game_state(self):
        for private in ({"sessionLoopState": "INGAME"},
                        {"matchPresenceData": {"sessionLoopState": "INGAME"}},
                        {"matchPresenceData": None, "sessionLoopState": "INGAME"},
                        {"matchPresenceData": {}, "sessionLoopState": "INGAME"}):
            entries = [None, {"puuid": "other"}, {"puuid": "self", "private": encoded(private)}]
            self.assertEqual(self.presences.get_game_state(entries), "INGAME")
        for private in ({}, {"matchPresenceData": []}, {"sessionLoopState": []}):
            self.assertIsNone(self.presences.game_state(private))

    def test_league_entries_and_bad_own_entries_do_not_hide_valorant(self):
        entries = [
            {"puuid": "self", "private": "bad"},
            {"puuid": "self", "product": "league_of_legends", "private": encoded({"sessionLoopState": "WRONG"})},
            {"puuid": "self", "championId": 1, "private": encoded({"sessionLoopState": "WRONG"})},
            {"puuid": "self", "private": encoded({"sessionLoopState": "MENUS"})},
        ]
        self.assertEqual(self.presences.get_game_state(entries), "MENUS")

    def test_wait_is_single_snapshot_without_polling_or_sleep(self):
        self.requests.fetch.return_value = {"presences": []}
        self.assertEqual(self.presences.wait_for_presence(["missing", "also-missing"]), [])
        self.requests.fetch.assert_called_once_with(url_type="local", endpoint="/chat/v4/presences", method="get")


if __name__ == "__main__":
    unittest.main()
