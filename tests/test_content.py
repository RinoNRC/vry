import unittest
from unittest.mock import Mock, patch

import requests

from src.content import Content


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(region="eu")
        self.content = Content(self.client, Mock())

    def test_no_current_season_is_safe(self):
        for payload in (None, {}, {"Seasons": []}, {"Seasons": [None, {}]}, {"Seasons": None}):
            with self.subTest(payload=payload):
                self.assertIsNone(self.content.get_latest_season_id(payload))
                self.assertIsNone(self.content.get_previous_season_id(payload))
        self.assertEqual(self.content.get_act_episode_from_act_id(None), {"act": None, "episode": None})

    def test_current_and_previous_season(self):
        payload = {"Seasons": [
            {"ID": "now", "Type": "act", "IsActive": True, "StartTime": "date"},
            {"ID": "before", "Type": "act", "EndTime": "date"},
        ]}
        self.assertEqual(self.content.get_latest_season_id(payload), "now")
        self.assertEqual(self.content.get_previous_season_id(payload), "before")

    def test_content_error_keeps_known_catalog(self):
        self.client.fetch.return_value = {"Seasons": []}
        self.assertEqual(self.content.get_content(), {"Seasons": []})
        self.client.fetch.return_value = None
        self.assertEqual(self.content.get_content(), {"Seasons": []})

    @patch("src.content.requests.get")
    def test_agents_and_icons_share_request_with_timeout(self, get):
        get.return_value.json.return_value = {"data": [
            {"uuid": "ABC", "displayName": "Sage", "displayIcon": "icon"}, None, {},
        ]}
        self.assertEqual(self.content.get_all_agents()["abc"], "Sage")
        self.assertEqual(self.content.get_agent_icons()["abc"], "icon")
        self.content.get_all_agents()
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["timeout"], (3, 10))

    @patch("src.content.requests.get")
    def test_optional_catalog_outage_is_safe(self, get):
        get.side_effect = requests.Timeout("secret")
        self.assertEqual(self.content.get_all_agents(), {None: None, "": ""})
        self.assertEqual(self.content.get_all_maps(), {"data": []})
        self.assertEqual(self.content.get_rank_icons(), {})
        self.assertNotIn("secret", str(self.content.log.call_args_list))

    @patch("src.content.requests.get")
    def test_malformed_maps_and_tiers_do_not_crash(self, get):
        get.return_value.json.return_value = {"data": [None, {}, {"mapUrl": None}]}
        maps = self.content.get_all_maps()
        self.assertEqual(self.content.get_map_urls(maps), {None: None})
        self.assertEqual(self.content.get_map_splashes(maps), {None: None})
        get.return_value.json.return_value = {"data": [{"tiers": None}]}
        self.assertEqual(self.content.get_rank_icons(), {})


if __name__ == "__main__":
    unittest.main()
