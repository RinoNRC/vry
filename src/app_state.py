import copy
import threading
import time


class AppStateStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._revision = 0
        self._status = "Starting"
        self._error = None
        self._heartbeat = {}
        self._loadouts = {}
        self._account = {}
        self._chat = []
        self._events = []
        self._updated_at = time.time()
        self._heartbeat_at = None
        self._heartbeat_history = []

    def set_status(self, status):
        with self._lock:
            if status != self._status:
                self._add_event("info", "Статус monitor", str(status))
            self._status = status
            self._error = None
            self._touch()

    def set_error(self, message):
        with self._lock:
            self._status = "Error"
            self._error = str(message)
            self._add_event("error", "Ошибка monitor", "Подробности доступны в блоке ошибки")
            self._touch()

    def publish(self, event_type, payload):
        data = copy.deepcopy(payload)
        with self._lock:
            if event_type == "heartbeat":
                previous_state = self._heartbeat.get("state")
                previous_match = self._heartbeat.get("matchId")
                self._heartbeat = data
                self._heartbeat_at = time.time()
                self._heartbeat_history.append(self._heartbeat_at)
                self._heartbeat_history = self._heartbeat_history[-60:]
                self._status = data.get("state", "Connected")
                self._error = None
                account_puuid = data.get("puuid")
                account_player = (data.get("players") or {}).get(account_puuid)
                if account_player:
                    previous_profile = self._account.get("profile", {})
                    self._account = {
                        "profile": previous_profile | account_player,
                        "state": data.get("state"),
                        "mode": data.get("mode"),
                        "map": data.get("map"),
                        "mapSplash": data.get("mapSplash"),
                        "server": data.get("server"),
                        "region": data.get("region"),
                        "matchId": data.get("matchId"),
                        "updatedAt": self._heartbeat_at,
                    }
                if data.get("state") != previous_state:
                    self._add_event(
                        "state",
                        "Состояние игры",
                        f"{previous_state or 'START'} -> {data.get('state', 'Unknown')}",
                    )
                if data.get("matchId") and data.get("matchId") != previous_match:
                    self._add_event(
                        "match",
                        "Новая игровая сессия",
                        f"{data.get('mode', 'Unknown')} / {data.get('map') or 'Unknown'}",
                    )
            elif event_type == "matchLoadout":
                self._loadouts = data
                self._add_event(
                    "data",
                    "Инвентари обновлены",
                    f"Игроков: {len(data.get('Players') or {})}",
                )
            elif event_type == "chat":
                self._chat.append(data)
                self._chat = self._chat[-100:]
            self._touch()

    def snapshot(self):
        with self._lock:
            return {
                "revision": self._revision,
                "status": self._status,
                "error": self._error,
                "heartbeat": copy.deepcopy(self._heartbeat),
                "loadouts": copy.deepcopy(self._loadouts),
                "account": copy.deepcopy(self._account),
                "chat": copy.deepcopy(self._chat),
                "events": copy.deepcopy(self._events),
                "started_at": self._started_at,
                "updated_at": self._updated_at,
                "heartbeat_at": self._heartbeat_at,
                "heartbeat_history": list(self._heartbeat_history),
            }

    def clear_events(self):
        with self._lock:
            self._events = []
            self._touch()

    def _add_event(self, level, title, message):
        event = {
            "time": time.time(),
            "level": level,
            "title": title,
            "message": message,
        }
        if self._events and all(
            self._events[-1].get(key) == event[key]
            for key in ("level", "title", "message")
        ):
            return
        self._events.append(event)
        self._events = self._events[-100:]

    def _touch(self):
        self._revision += 1
        self._updated_at = time.time()


app_state = AppStateStore()
