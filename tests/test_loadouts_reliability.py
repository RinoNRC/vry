import copy
import unittest
from unittest.mock import Mock, patch

import requests

from src.constants import sockets
from src.Loadouts import Loadouts


def response(data):
    result = Mock()
    result.json.return_value = {"data": data}
    return result


class LoadoutsReliabilityTests(unittest.TestCase):
    def setUp(self):
        http_patch = patch("src.Loadouts.requests.get")
        self.http = http_patch.start()
        self.addCleanup(http_patch.stop)
        self.client = Mock()
        self.log = Mock()
        self.store = Mock()
        self.colors = Mock()
        self.colors.get_rgb_color_from_skin.return_value = (1, 2, 3)
        self.loadouts = Loadouts(self.client, self.log, self.colors, self.store, "Ascent")
        self.players = [{
            "Subject": "player", "CharacterID": "agent", "TeamID": "Blue",
            "PlayerIdentity": {"AccountLevel": 42, "PlayerTitleID": "title", "PlayerCardID": "card"},
        }]
        self.inventory = {
            "Items": {"weapon": {"Sockets": {
                sockets["skin"]: {"Item": {"ID": "skin"}},
                sockets["skin_chroma"]: {"Item": {"ID": "chroma"}},
                sockets["skin_buddy"]: {"Item": {"ID": "buddy"}},
            }}},
            "Expressions": {"AESSelections": [{
                "TypeID": "d5f120f8-ff8c-4aac-92ea-f2b5acbe9475", "AssetID": "spray",
            }]},
        }
        self.payload = {"Loadouts": [{
            "Subject": "player", "CharacterID": "agent", "Loadout": self.inventory,
        }]}
        self.client.fetch.return_value = self.payload
        self.skin = {"uuid": "skin", "displayName": "Fancy Vandal", "chromas": [
            {"uuid": "chroma", "displayIcon": "chroma-icon"},
        ]}
        self.skins = response([self.skin])
        self.catalogs = {
            "weapons": [{"uuid": "weapon", "displayName": "Vandal", "skins": [self.skin]}],
            "sprays": [{"uuid": "spray", "displayName": "Spray", "displayIcon": "spray-icon",
                        "fullTransparentIcon": "spray-full"}],
            "buddies": [{"uuid": "buddy", "displayIcon": "buddy-icon"}],
            "agents": [{"uuid": "agent", "displayName": "Agent", "displayIcon": "agent-icon"}],
            "playertitles": [{"uuid": "title", "titleText": "Title"}],
            "playercards": [{"uuid": "card", "largeArt": "card-art"}],
        }
        self.http.side_effect = lambda url, **kwargs: response(self.catalogs[url.rsplit("/", 1)[-1]])

    def get(self, **kwargs):
        return self.loadouts.get_match_loadouts(
            "match", kwargs.pop("players", self.players), "Vandal", self.skins,
            {"player": "Name"}, **kwargs)

    def assert_empty(self, result):
        self.assertEqual(result[0], {})
        self.assertEqual(result[1]["Players"], {})
        self.assertIsInstance(result[1]["time"], int)
        self.assertEqual(result[1]["map"], "Ascent")
        self.store.publish.assert_called_with("matchLoadout", result[1])

    def test_missing_or_malformed_loadouts_skip_all_catalogs(self):
        for payload in (None, [], {}, {"Loadouts": None}, {"Loadouts": {}},
                        {"Loadouts": []}, {"Loadouts": [None, {}, "bad"]},
                        {"Loadouts": [{"Subject": "player", "CharacterID": "agent", "Loadout": None}]}):
            with self.subTest(payload=payload):
                self.client.fetch.return_value = payload
                self.assert_empty(self.get())
        self.http.assert_not_called()
        self.log.assert_not_called()

    def test_fetch_exception_is_optional_and_not_logged(self):
        self.client.fetch.side_effect = RuntimeError("private response must not be logged")
        self.assert_empty(self.get())
        self.http.assert_not_called()
        self.log.assert_not_called()

    def test_catalog_failures_have_shared_negative_ttl_and_recover(self):
        catalog_response = self.http.side_effect
        for failure in (requests.Timeout("private"), ValueError("private")):
            with self.subTest(failure=type(failure).__name__):
                self.loadouts._reference_data_cache.clear()
                self.loadouts._reference_retry_at = 0
                self.http.reset_mock()
                self.http.side_effect = failure
                with patch("src.Loadouts.time.monotonic", return_value=100):
                    self.assert_empty(self.get())
                    self.assert_empty(self.get())
                    with self.assertRaises(ValueError):
                        self.loadouts._get_reference_data("sprays")
                    self.http.assert_called_once()
                with patch("src.Loadouts.time.monotonic", return_value=114.9):
                    self.assert_empty(self.get())
                    self.http.assert_called_once()
                self.http.side_effect = catalog_response
                with patch("src.Loadouts.time.monotonic", return_value=115):
                    self.assertIn("player", self.get()[1]["Players"])
                self.assertEqual(self.http.call_count, 7)
        self.log.assert_not_called()

    def test_malformed_catalogs_and_http_status_errors_are_cached(self):
        for payload in (None, {}, {"data": None}, {"data": {}}, {"data": [None]}):
            with self.subTest(payload=payload):
                self.loadouts._reference_retry_at = 0
                self.http.reset_mock()
                reply = Mock()
                reply.json.return_value = payload
                self.http.side_effect = None
                self.http.return_value = reply
                self.assert_empty(self.get())
                self.assert_empty(self.get())
                self.http.assert_called_once()
        self.loadouts._reference_retry_at = 0
        self.http.return_value.raise_for_status.side_effect = requests.HTTPError("private")
        self.assert_empty(self.get())
        self.log.assert_not_called()

    def test_secondary_catalog_failure_preserves_weapon_names(self):
        catalog_response = self.http.side_effect

        def fetch(url, **kwargs):
            if url.endswith("/sprays"):
                raise requests.Timeout("private")
            return catalog_response(url, **kwargs)

        self.http.side_effect = fetch
        first = self.get()
        self.assertIn("player", first[0])
        self.assertEqual(first[1]["Players"], {})
        second = self.get()
        self.assertEqual(first[0], second[0])
        self.assertEqual(self.http.call_count, 2)
        self.log.assert_not_called()

    def test_malformed_skin_response_does_not_discard_full_loadout(self):
        for payload in (None, {}, {"data": None}, {"data": [None]}):
            with self.subTest(payload=payload):
                self.skins.json.return_value = payload
                result = self.get()
                self.assertEqual(result[0], {})
                self.assertIn("player", result[1]["Players"])
        self.log.assert_not_called()

    def test_malformed_nested_data_does_not_escape(self):
        for inventory in ({"Items": {"weapon": None}},
                          {"Items": {"weapon": {"Sockets": None}}},
                          {"Items": {}, "Expressions": None}):
            with self.subTest(inventory=inventory):
                self.payload["Loadouts"][0]["Loadout"] = inventory
                self.assert_empty(self.get())
        self.log.assert_not_called()

    def test_success_schema_and_catalog_cache_are_preserved(self):
        original = copy.deepcopy(self.payload)
        with patch("src.Loadouts.hide_names", False), patch("src.Loadouts.color", side_effect=lambda text, **_: text):
            result = self.get()
            self.assertEqual(result[0], {"player": "Fancy"})
            self.assertEqual(result[1]["Players"], {"player": {
                "Name": "Name", "Team": "Blue", "Level": 42, "Title": "Title",
                "PlayerCard": "card-art", "AgentArtworkName": "AgentArtwork", "Agent": "agent-icon",
                "Sprays": {0: {"displayName": "Spray", "displayIcon": "spray-icon",
                               "fullTransparentIcon": "spray-full"}},
                "Weapons": {"weapon": {"skin": "skin", "skin_chroma": "chroma", "skin_buddy": "buddy",
                                       "buddy_displayIcon": "buddy-icon", "weapon": "Vandal",
                                       "skinDisplayName": "Fancy Vandal", "skinDisplayIcon": "chroma-icon"}},
            }})
            self.get()
        self.assertEqual(self.http.call_count, 6)
        for call in self.http.call_args_list:
            self.assertEqual(call.kwargs["timeout"], (3, 10))
        self.assertEqual(self.payload, original)
        self.client.fetch.assert_called_with("glz", "/core-game/v1/matches/match/loadouts", "get")
        self.store.publish.assert_called_with("matchLoadout", result[1])

    def test_pregame_success_keeps_existing_schema(self):
        self.client.fetch.return_value = {"Loadouts": [{
            "Subject": "player", "CharacterID": "agent", **self.inventory,
        }]}
        with patch("src.Loadouts.color", side_effect=lambda text, **_: text):
            result = self.get(players={"AllyTeam": {"Players": self.players}}, state="pregame")
        self.assertEqual(result[0], {"player": "Fancy"})
        self.assertEqual(result[1]["Players"], {})
        self.client.fetch.assert_called_with("glz", "/pregame/v1/matches/match/loadouts", "get")

    def test_publish_failure_does_not_escape(self):
        self.store.publish.side_effect = RuntimeError("private")
        self.assertIn("player", self.get()[1]["Players"])
        self.log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
