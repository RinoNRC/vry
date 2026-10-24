import re
import websockets
import websockets.client
import ssl
import base64
import json
import asyncio
from colr import color
from collections import deque
from src.presences import Presences


class Ws:
    def __init__(self, lockfile, Requests, cfg, colors, hide_names, state_store, rpc=None):
        self.lockfile = lockfile
        self.Requests = Requests
        self.log = Requests.log
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        self.id_seen = deque(maxlen=1000)
        self.cfg = cfg
        self.player_data = {}
        self.messages = 0
        self.colors = colors
        self.hide_names = hide_names
        self.up = "\033[A"
        limit = cfg.chat_limit
        self.chat_limit = max(1, limit) if isinstance(limit, int) and not isinstance(limit, bool) else 10
        self.message_history = deque(maxlen=self.chat_limit)
        self.state_store = state_store
        self.rpc = rpc
        self.on_idle = None

    def set_player_data(self, player_data):
        self.player_data = player_data if isinstance(player_data, dict) else {}

    async def recconect_to_websocket(self, initial_game_state):
        local_headers = {
            'Authorization': 'Basic ' + base64.b64encode(('riot:' + self.lockfile['password']).encode()).decode()
        }
        url = f"wss://127.0.0.1:{self.lockfile['port']}"

        max_retries = 5
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                async with websockets.connect(url, ssl=self.ssl_context, extra_headers=local_headers) as websocket:
                    await websocket.send('[5, "OnJsonApiEvent_chat_v4_presences"]')
                    if self.cfg.get_feature_flag("game_chat"):
                        await websocket.send('[5, "OnJsonApiEvent_chat_v6_messages"]')

                    subscribed_chat = bool(self.cfg.get_feature_flag("game_chat"))
                    maintenance_at = 0
                    receive_task = asyncio.create_task(websocket.recv())
                    try:
                        while True:
                            now = asyncio.get_running_loop().time()
                            if now >= maintenance_at:
                                if self.on_idle is not None:
                                    self.on_idle()
                                enabled_chat = bool(self.cfg.get_feature_flag("game_chat"))
                                if enabled_chat != subscribed_chat:
                                    operation = 5 if enabled_chat else 6
                                    await websocket.send(f'[{operation}, "OnJsonApiEvent_chat_v6_messages"]')
                                    subscribed_chat = enabled_chat
                                maintenance_at = now + 2
                            done, _ = await asyncio.wait({receive_task}, timeout=max(0, maintenance_at - now))
                            if not done:
                                continue
                            response = receive_task.result()
                            result = self.handle(response, initial_game_state)
                            if result is not None:
                                return result
                            receive_task = asyncio.create_task(websocket.recv())
                    finally:
                        if not receive_task.done():
                            receive_task.cancel()
                        await asyncio.gather(receive_task, return_exceptions=True)
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.InvalidURI, websockets.exceptions.InvalidHandshake, ConnectionRefusedError, OSError):
                self.log(f"Websocket failed (attempt {attempt + 1}/{max_retries}).")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    self.log(f"Websocket failed after {max_retries} attempts.")
                    return "DISCONNECTED"
            except Exception:
                self.log("Unexpected websocket error.")
                return "DISCONNECTED"

        return "DISCONNECTED"

    def handle(self, m, initial_game_state):
        try:
            resp_json = json.loads(m)
        except (ValueError, TypeError, UnicodeError):
            return None
        if not isinstance(resp_json, list) or len(resp_json) < 3 or not isinstance(resp_json[2], dict):
            return None
        event = resp_json[2]
        data = event.get("data")
        if not isinstance(data, dict):
            return None

        if event.get("uri") == "/chat/v4/presences":
            presences = data.get("presences")
            if not isinstance(presences, list):
                return None
            next_state = None
            for presence in presences:
                if not isinstance(presence, dict) or presence.get("puuid") != self.Requests.puuid:
                    continue
                if presence.get("championId") is not None or presence.get("product") == "league_of_legends":
                    continue
                private_data = Presences.decode_private(presence.get("private"))
                state = Presences.game_state(private_data)
                if state is None:
                    continue
                if self.cfg.get_feature_flag("discord_rpc") and self.rpc is not None:
                    self.rpc.set_rpc(private_data)
                next_state = state
            if next_state is not None and next_state != initial_game_state:
                self.messages = 0
                self.message_history.clear()
                return next_state

        elif event.get("uri") == "/chat/v6/messages" and self.cfg.get_feature_flag("game_chat"):
            messages = data.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    self._handle_message(message)
        return None

    def _handle_message(self, message):
        if not isinstance(message, dict):
            return
        cid = message.get("cid")
        message_id = message.get("id")
        msg_puuid = message.get("puuid")
        body = message.get("body")
        if not isinstance(cid, str) or "ares-coregame" not in cid:
            return
        if not isinstance(message_id, str) or not message_id or message_id in self.id_seen:
            return
        if not isinstance(msg_puuid, str) or not msg_puuid or not isinstance(body, str):
            return

        own_data = self.player_data.get(self.Requests.puuid)
        self.ally_team = own_data.get("team") if isinstance(own_data, dict) else None
        msg_player_data = self.player_data.get(msg_puuid)
        if not isinstance(msg_player_data, dict):
            msg_player_data = {}
        if msg_puuid == self.Requests.puuid:
            clr = (221, 224, 41)
        elif msg_player_data.get("team") == self.ally_team:
            clr = (76, 151, 237)
        else:
            clr = (238, 77, 77)

        chat_indicator = cid.split("@")[0].rsplit("-", 1)[-1]
        chat_prefix = color("[Team]", fore=(116, 162, 214)) if chat_indicator == "blue" else "[All]"
        agent_id = msg_player_data.get("agent")
        agent = self.colors.get_agent_from_uuid(agent_id.lower() if isinstance(agent_id, str) else "") or ""
        game_name, game_tag = message.get("game_name"), message.get("game_tag")
        name = f"{game_name}#{game_tag}" if isinstance(game_name, str) and isinstance(game_tag, str) else "Unknown"
        ignored = self.player_data.get("ignore")
        ignored = ignored if isinstance(ignored, (list, tuple, set)) else []
        hidden = self.hide_names and msg_puuid not in ignored and (
            msg_player_data.get("streamer_mode") or not msg_player_data
        )
        payload = {
            "time": message.get("time"), "puuid": msg_puuid, "self": msg_puuid == self.Requests.puuid,
            "group": re.sub(r"\[|\]", "", self.colors.escape_ansi(chat_prefix)),
            "agent": self.colors.escape_ansi(agent), "text": body,
        }
        if hidden:
            label = self.colors.escape_ansi(agent) or "Unknown"
            self.print_message(f"{chat_prefix} {color(label, clr)}: {body}")
        else:
            agent_str = f" ({agent})" if agent else ""
            self.print_message(f"{chat_prefix} {color(name, clr)}{agent_str}: {body}")
            payload["player"] = name
        self.state_store.publish("chat", payload)
        self.id_seen.append(message_id)

    def print_message(self, message):
        self.messages = min(self.messages + 1, self.chat_limit + 1)
        if self.messages > self.chat_limit:
            print(self.up * self.chat_limit, end="")
            for i in range(len(self.message_history) - self.chat_limit + 1, len(self.message_history)):
                print(self.message_history[i] + " " * max([0, len(self.colors.escape_ansi(self.message_history[i-1]).encode('utf8')) - len(self.colors.escape_ansi(self.message_history[i]).encode('utf8'))]))
            print(message + " " * max([0, len(self.colors.escape_ansi(self.message_history[-1]).encode('utf8')) - len(self.colors.escape_ansi(message).encode('utf8'))]))
        else:
            print(message)

        self.message_history.append(message)
