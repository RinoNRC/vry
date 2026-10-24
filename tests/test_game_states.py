import unittest
from unittest.mock import Mock

from src.states.coregame import Coregame
from src.states.pregame import Pregame


class GameStatesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(puuid="self")

    def test_coregame_keeps_id_from_same_lookup(self):
        self.client.fetch.side_effect = [
            {"MatchID": "match"}, {"Players": [], "MapID": "bind"},
        ]
        game = Coregame(self.client, Mock())
        self.assertEqual(game.get_coregame_stats()["MapID"], "bind")
        self.assertEqual(game.match_id, "match")
        self.assertEqual(self.client.fetch.call_count, 2)

    def test_lookup_errors_do_not_retry_immediately_or_crash(self):
        for cls, method in ((Coregame, "get_coregame_stats"), (Pregame, "get_pregame_stats")):
            for payload in (None, [], {}, {"errorCode": "RESOURCE_NOT_FOUND"}):
                with self.subTest(cls=cls, payload=payload):
                    self.client.fetch.reset_mock()
                    self.client.fetch.return_value = payload
                    instance = cls(self.client, Mock())
                    self.assertIsNone(getattr(instance, method)())
                    self.assertEqual(instance.match_id, 0)
                    self.client.fetch.assert_called_once()

    def test_malformed_match_response_returns_none(self):
        for cls, method in ((Coregame, "get_coregame_stats"), (Pregame, "get_pregame_stats")):
            for payload in (None, [], {}, {"errorCode": "RESOURCE_NOT_FOUND"}):
                with self.subTest(cls=cls, payload=payload):
                    self.client.fetch.side_effect = [{"MatchID": "match"}, payload]
                    self.assertIsNone(getattr(cls(self.client, Mock()), method)())

    def test_pregame_valid_response(self):
        data = {"ID": "match", "AllyTeam": {"Players": []}, "Teams": [{"TeamID": "Blue"}]}
        self.client.fetch.side_effect = [{"MatchID": "match"}, data]
        self.assertEqual(Pregame(self.client, Mock()).get_pregame_stats(), data)


if __name__ == "__main__":
    unittest.main()
