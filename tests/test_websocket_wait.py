import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.websocket import Ws


class WebsocketWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_callback_applies_settings_without_http_or_state_change(self):
        client = Mock(puuid="self")
        flags = {"game_chat": True, "discord_rpc": False}
        cfg = Mock(chat_limit=2)
        cfg.get_feature_flag.side_effect = lambda key: flags.get(key, False)
        ws = Ws({"password": "test", "port": 1}, client, cfg, Mock(), True, Mock())
        socket = Mock()
        socket.send = AsyncMock()
        release = asyncio.Event()

        async def receive():
            await release.wait()
            return json.dumps([8, "event", {"uri": "/chat/v4/presences", "data": {"presences": [
                {"puuid": "self", "private": {"sessionLoopState": "INGAME"}},
            ]}}])

        socket.recv = receive
        connection = Mock()
        connection.__aenter__ = AsyncMock(return_value=socket)
        connection.__aexit__ = AsyncMock(return_value=False)

        def idle():
            flags["game_chat"] = False
            release.set()

        ws.on_idle = Mock(side_effect=idle)
        with patch("src.websocket.websockets.connect", return_value=connection):
            self.assertEqual(await ws.recconect_to_websocket("MENUS"), "INGAME")
        ws.on_idle.assert_called_once()
        self.assertEqual([call.args[0] for call in socket.send.call_args_list], [
            '[5, "OnJsonApiEvent_chat_v4_presences"]',
            '[5, "OnJsonApiEvent_chat_v6_messages"]',
            '[6, "OnJsonApiEvent_chat_v6_messages"]',
        ])
        client.fetch.assert_not_called()

    async def test_cancellation_cleans_up_pending_receive(self):
        client = Mock(puuid="self")
        cfg = Mock(chat_limit=2)
        cfg.get_feature_flag.return_value = False
        ws = Ws({"password": "test", "port": 1}, client, cfg, Mock(), True, Mock())
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def receive():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        socket = Mock(send=AsyncMock(), recv=receive)
        connection = Mock()
        connection.__aenter__ = AsyncMock(return_value=socket)
        connection.__aexit__ = AsyncMock(return_value=False)
        with patch("src.websocket.websockets.connect", return_value=connection):
            task = asyncio.create_task(ws.recconect_to_websocket("MENUS"))
            await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(cancelled.is_set())
        client.fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
