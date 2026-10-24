import base64
import json
import unittest
from unittest.mock import Mock

from src.presences import Presences
from src.states.menu import Menu


def presence(puuid, private):
    return {"puuid": puuid, "private": base64.b64encode(json.dumps(private).encode()).decode()}


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.requests = Mock(puuid="self")
        self.requests.fetch.return_value = None
        self.log = Mock()
        self.menu = Menu(self.requests, self.log, Presences(self.requests, self.log))
        self.flat = {"isValid": True, "partyId": "party", "partySize": 2, "accountLevel": 50}
        self.nested = {"isValid": True, "partyPresenceData": {"partyId": "party", "partySize": 2},
                       "playerPresenceData": {"accountLevel": 100}}

    def test_party_json_groups_flat_and_nested_without_duplicates(self):
        entries = [presence("self", self.flat), presence("other", self.nested), presence("other", self.nested),
                   presence("outside", self.flat), None, {}, {"puuid": "self", "private": "bad"}]
        self.assertEqual(self.menu.get_party_json(["self", "other"], entries), {"party": ["self", "other"]})
        self.requests.fetch.assert_not_called()

    def test_party_json_unknown_or_malformed_data(self):
        for private in ({"isValid": True}, {"isValid": True, "partyPresenceData": []},
                        {**self.flat, "partyId": []}, {**self.flat, "partyId": "00000000-0000-0000-0000-000000000000"},
                        {**self.flat, "partyId": " "}, {**self.flat, "isValid": False}):
            entries = [presence("self", private), presence("other", private)]
            with self.subTest(private=private):
                self.assertEqual(self.menu.get_party_json(["self", "other"], entries), {})
        for entries in (None, {}, "bad", [None, []]):
            self.assertEqual(self.menu.get_party_json(["self"], entries), {})
        self.assertEqual(self.menu.get_party_json(["self"], [presence("self", self.flat)]), {})

    def test_shared_party_id_is_enough_without_validity_or_size_fields(self):
        for size in (None, "2", 1):
            private = {"partyId": "party", "partySize": size}
            entries = [presence("self", private), presence("other", {"partyPresenceData": private})]
            self.assertEqual(self.menu.get_party_json(["self", "other"], entries), {"party": ["self", "other"]})
        self.requests.fetch.assert_not_called()

    def test_own_api_roster_fills_missing_presence_without_extra_requests(self):
        members = [{"Subject": "self"}, {"Subject": "friend"}, {"Subject": "outside-match"}]
        entries = [presence("self", self.flat)]
        self.assertEqual(self.menu.get_party_json(["self", "friend", "solo"], entries, members), {
            "own:self": ["friend", "self"],
        })
        self.requests.fetch.assert_not_called()

    def test_api_roster_overrides_stale_own_presence_but_preserves_other_groups(self):
        entries = [presence(puuid, self.flat) for puuid in ("self", "former", "friend")]
        entries += [presence(puuid, {"partyId": "enemy-party"}) for puuid in ("enemy1", "enemy2")]
        players = ["self", "friend", "former", "enemy1", "enemy2"]
        groups = self.menu.get_party_json(players, entries, [{"Subject": "self"}, {"Subject": "friend"}])
        self.assertEqual(groups, {"own:self": ["friend", "self"], "enemy-party": ["enemy1", "enemy2"]})
        solo = self.menu.get_party_json(players, entries, [{"Subject": "self"}])
        self.assertEqual(solo, {"enemy-party": ["enemy1", "enemy2"]})

    def test_unrelated_roster_cannot_override_own_party(self):
        entries = [presence("self", self.flat), presence("other", self.flat)]
        self.assertEqual(self.menu.get_party_json(["self", "other"], entries, [{"Subject": "other"}]), {
            "party": ["self", "other"],
        })

    def test_party_labels_are_consistent_for_interleaved_players(self):
        groups = {"second": ["b1", "b2"], "first": ["a1", "a2", "a3"]}
        labels = self.menu.get_party_labels(groups)
        self.assertEqual([labels[p]["partyNumber"] for p in ("a1", "b1", "a2", "b2", "a3")], [1, 2, 1, 2, 1])
        self.assertEqual(labels["a3"]["partySize"], 3)
        self.assertEqual(self.menu.get_party_labels(dict(reversed(list(groups.items())))), labels)

    def test_fallback_accepts_party_fields_without_is_valid(self):
        entries = [presence("self", {"partyId": "party"}), presence("friend", {"partyPresenceData": {"partyId": "party"}})]
        self.assertEqual([p["Subject"] for p in self.menu.get_party_members("self", entries)], ["self", "friend"])

    def test_api_roster_is_preferred_and_normalized(self):
        self.requests.fetch.side_effect = [
            {"CurrentPartyID": "party"},
            {"Members": [None, {"Subject": []}, {"Subject": "self", "PlayerIdentity": {"AccountLevel": 10}},
                         {"Subject": "self"}, {"subject": "other", "playerIdentity": "invalid"},
                         {"Subject": "third", "PlayerIdentity": {"AccountLevel": -1}}]},
        ]
        self.assertEqual(self.menu.get_party_members("self", None), [
            {"Subject": "self", "PlayerIdentity": {"AccountLevel": 10}},
            {"Subject": "other", "PlayerIdentity": {"AccountLevel": 0}},
            {"Subject": "third", "PlayerIdentity": {"AccountLevel": 0}},
        ])
        self.assertEqual(self.requests.fetch.call_count, 2)

    def test_fallback_validates_entries_and_uses_shared_flat_nested_fields(self):
        entries = [None, [], {}, presence("self", self.flat), presence("other", self.nested),
                   presence("other", self.nested), presence("unrelated", {**self.flat, "partyId": "elsewhere"}),
                   presence("bad-level", {**self.flat, "accountLevel": "secret"}),
                   presence([], self.flat), {"puuid": "bad", "private": "!!!"},
                   {**presence("league", self.flat), "product": "league_of_legends"}]
        self.assertEqual(self.menu.get_party_members("self", entries), [
            {"Subject": "self", "PlayerIdentity": {"AccountLevel": 50}},
            {"Subject": "other", "PlayerIdentity": {"AccountLevel": 100}},
            {"Subject": "bad-level", "PlayerIdentity": {"AccountLevel": 0}},
        ])
        self.assertEqual(self.requests.fetch.call_count, 1)

    def test_bad_api_and_absent_own_party_are_harmless(self):
        for response in (None, {}, [], {"CurrentPartyID": []}):
            self.requests.fetch.return_value = response
            for entries in (None, [], [None], [presence("self", {"isValid": True})]):
                self.assertEqual(self.menu.get_party_members("self", entries), [])
        self.requests.fetch.side_effect = RuntimeError("private-secret")
        self.assertEqual(self.menu.get_party_members("self", [presence("self", self.flat)])[0]["Subject"], "self")
        self.assertNotIn("private-secret", str(self.log.call_args_list))

    def test_invalid_self_does_not_fetch(self):
        self.assertEqual(self.menu.get_party_members([], None), [])
        self.requests.fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
