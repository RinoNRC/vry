import unittest
from unittest.mock import Mock, patch

from src.names import Names


def response(payload, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    return result


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.names = Names(self.client, Mock())

    def test_batch_deduplicates_and_caches_only_requested_valid_names(self):
        self.client.fetch.return_value = response([
            {"Subject": "a", "GameName": "Name", "TagLine": "EU"},
            {"Subject": "unrequested", "GameName": "Other", "TagLine": "EU"},
            {"Subject": "b", "GameName": None, "TagLine": "EU"},
        ])
        with patch("src.names.time.monotonic", return_value=0):
            result = self.names.get_multiple_names_from_puuid(["a", "b", "a"])
            self.assertEqual(result, {"a": "Name#EU", "b": "Unknown"})
            self.client.fetch.assert_called_once_with("pd", "/name-service/v2/players", "put", json=["a", "b"])
            self.assertEqual(self.names.get_name_from_puuid("a"), "Name#EU")
            self.names.get_multiple_names_from_puuid(["b"])
            self.assertEqual(self.client.fetch.call_count, 1)
            self.assertNotIn("unrequested", self.names._cache)
        with patch("src.names.time.monotonic", return_value=16):
            self.names.get_name_from_puuid("b")
            self.assertEqual(self.client.fetch.call_args.kwargs["json"], ["b"])

    def test_ttl_and_clear(self):
        self.client.fetch.return_value = response([{"Subject": "a", "GameName": "Name", "TagLine": ""}])
        with patch("src.names.time.monotonic", return_value=0):
            self.assertEqual(self.names.get_name_from_puuid("a"), "Name")
        with patch("src.names.time.monotonic", return_value=301):
            self.names.get_name_from_puuid("a")
            self.assertEqual(self.client.fetch.call_count, 2)
            self.names.clear_cache()
            self.names.get_name_from_puuid("a")
            self.assertEqual(self.client.fetch.call_count, 3)

    def test_empty_roster_does_not_request(self):
        self.assertEqual(self.names.get_names_from_puuids([]), {})
        self.client.fetch.assert_not_called()

    def test_failures_have_safe_fallback_and_no_immediate_repeat(self):
        for payload in ({"errorCode": "BAD_CLAIMS"}, None, [None], []):
            with self.subTest(payload=payload):
                self.names.clear_cache()
                self.client.fetch.reset_mock()
                self.client.fetch.return_value = response(payload)
                self.assertEqual(self.names.get_name_from_puuid("a"), "Unknown")
                self.assertEqual(self.names.get_name_from_puuid("a"), "Unknown")
                self.client.fetch.assert_called_once()
        self.names.clear_cache()
        self.client.fetch.side_effect = TimeoutError("secret")
        self.assertEqual(self.names.get_name_from_puuid("a"), "Unknown")
        self.assertNotIn("secret", str(self.names.log.call_args_list))


if __name__ == "__main__":
    unittest.main()
