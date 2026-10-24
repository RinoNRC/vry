import base64
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from src.websocket import Ws


def event(uri, field, entries):
    return json.dumps([8, "event", {"uri": uri, "data": {field: entries}}])


def own_presence(private):
    return {"puuid": "self", "private": base64.b64encode(json.dumps(private).encode()).decode()}


def chat(message_id="1", puuid="other", **fields):
    return {"id": message_id, "puuid": puuid, "cid": "ares-coregame-match-blue@server", "body": "hello",
            "game_name": "PrivateName", "game_tag": "Tag", "time": "now", **fields}


class WebsocketTests(unittest.TestCase):
    def setUp(self):
        self.requests = Mock(puuid="self")
        self.cfg = Mock(chat_limit=2)
        self.flags = {"game_chat": True, "discord_rpc": True}
        self.cfg.get_feature_flag.side_effect = lambda flag: self.flags.get(flag, False)
        self.colors = Mock()
        self.colors.get_agent_from_uuid.return_value = "Sage"
        self.colors.escape_ansi.side_effect = lambda text: text
        self.store = Mock()
        self.rpc = Mock()
        self.ws = Ws({}, self.requests, self.cfg, self.colors, True, self.store, self.rpc)
        self.ws.set_player_data({"self": {"team": "Blue"}, "other": {"team": "Blue", "agent": "agent", "streamer_mode": True}})

    def test_malformed_frames_are_ignored_without_private_logging(self):
        frames = [None, "", "not-json-private-secret", b"\xff", "null", "{}", "[]", "[8]", "[8,0,null]",
                  json.dumps([8, 0, {"uri": "/chat/v4/presences", "data": []}]),
                  event("/chat/v4/presences", "presences", None),
                  event("/chat/v4/presences", "presences", [None, [], {}, {"puuid": "self", "private": "!!!private-secret"}]),
                  event("/chat/v4/presences", "presences", [own_presence([]), own_presence(None)]),
                  event("/chat/v6/messages", "messages", [None, [], {}, chat(cid=[]), chat(id=[]), chat(puuid=[]), chat(body=None)])]
        for frame in frames:
            with self.subTest(frame=frame):
                self.assertIsNone(self.ws.handle(frame, "MENUS"))
        self.requests.log.assert_not_called()
        self.store.publish.assert_not_called()

    def test_own_presence_can_be_second_and_uses_shared_flat_nested_handling(self):
        for private in ({"sessionLoopState": "INGAME"},
                        {"matchPresenceData": {"sessionLoopState": "INGAME"}},
                        {"matchPresenceData": None, "sessionLoopState": "INGAME"}):
            self.ws.message_history.append("old")
            self.ws.messages = 1
            frame = event("/chat/v4/presences", "presences", [None, {"puuid": "other"}, own_presence(private)])
            self.assertEqual(self.ws.handle(frame, "MENUS"), "INGAME")
            self.assertEqual(list(self.ws.message_history), [])
            self.assertEqual(self.ws.messages, 0)
            self.rpc.set_rpc.assert_called_with(private)
        self.requests.fetch.assert_not_called()

    def test_unknown_presence_league_and_disabled_rpc(self):
        frame = event("/chat/v4/presences", "presences", [
            own_presence({"matchPresenceData": []}),
            {**own_presence({"sessionLoopState": "WRONG"}), "product": "league_of_legends"},
            {**own_presence({"sessionLoopState": "WRONG"}), "championId": 1},
        ])
        self.assertIsNone(self.ws.handle(frame, "MENUS"))
        self.rpc.set_rpc.assert_not_called()
        self.flags["discord_rpc"] = False
        self.assertIsNone(self.ws.handle(event("/chat/v4/presences", "presences", [own_presence({"sessionLoopState": "MENUS"})]), "MENUS"))
        self.rpc.set_rpc.assert_not_called()

    def test_all_chat_messages_processed_and_hidden_fields_not_published(self):
        frame = event("/chat/v6/messages", "messages", [None, chat("1"), chat("2", "unknown"), chat("1")])
        with redirect_stdout(io.StringIO()) as output:
            self.ws.handle(frame, "INGAME")
        self.assertEqual(self.store.publish.call_count, 2)
        for call in self.store.publish.call_args_list:
            self.assertNotIn("player", call.args[1])
            self.assertNotIn("PrivateName", json.dumps(call.args[1]))
        self.assertNotIn("PrivateName", output.getvalue())
        self.assertEqual(list(self.ws.id_seen), ["1", "2"])

    def test_hide_flag_and_ignore_list_preserve_existing_behavior(self):
        for hide_names, ignored in ((False, []), (True, ["other"])):
            self.ws.hide_names = hide_names
            self.ws.player_data["ignore"] = ignored
            self.ws.id_seen.clear()
            with redirect_stdout(io.StringIO()):
                self.ws.handle(event("/chat/v6/messages", "messages", [chat()]), "INGAME")
            self.assertEqual(self.store.publish.call_args.args[1]["player"], "PrivateName#Tag")
        self.flags["game_chat"] = False
        self.store.publish.reset_mock()
        self.ws.handle(event("/chat/v6/messages", "messages", [chat("disabled")]), "INGAME")
        self.store.publish.assert_not_called()

    def test_missing_optional_chat_fields_and_unknown_player_are_harmless(self):
        self.ws.set_player_data(None)
        message = {"id": "minimal", "puuid": "unknown", "cid": "ares-coregame", "body": "hello"}
        with redirect_stdout(io.StringIO()):
            self.ws.handle(event("/chat/v6/messages", "messages", [message]), "INGAME")
        payload = self.store.publish.call_args.args[1]
        self.assertIsNone(payload["time"])
        self.assertNotIn("player", payload)

    def test_chat_history_and_deduplication_are_bounded(self):
        with redirect_stdout(io.StringIO()):
            for number in range(1100):
                self.ws.handle(event("/chat/v6/messages", "messages", [chat(str(number))]), "INGAME")
        self.assertEqual(len(self.ws.id_seen), 1000)
        self.assertEqual(len(self.ws.message_history), 2)
        self.assertEqual(self.ws.messages, 3)
        self.assertEqual(self.ws.id_seen[-1], "1099")

    def test_chat_limit_one_and_invalid_limit_do_not_crash(self):
        for limit in (0, 1, None, "bad"):
            self.cfg.chat_limit = limit
            ws = Ws({}, self.requests, self.cfg, self.colors, True, self.store)
            with redirect_stdout(io.StringIO()):
                for number in range(12):
                    ws.print_message(str(number))
            self.assertLessEqual(len(ws.message_history), ws.chat_limit)


if __name__ == "__main__":
    unittest.main()
