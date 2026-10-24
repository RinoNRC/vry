import copy
import threading
import time


class AppStateStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._revision = 0
        self._history_revision = 0
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
            if event_type == "disconnected":
                self._heartbeat = {}
                self._loadouts = {}
                self._account = {}
                self._chat = []
                self._status = "DISCONNECTED"
                self._error = None
                self._add_event("warning", "Клиент отключён", "Ожидание повторного подключения")
            elif event_type == "heartbeat":
                previous_state = self._heartbeat.get("state")
                previous_match = self._heartbeat.get("matchId")
                if self._stats_context(data) == self._stats_context(self._heartbeat):
                    for puuid, player in (data.get("players") or {}).items():
                        recent = (self._heartbeat.get("players") or {}).get(puuid, {}).get("recentStats")
                        if recent:
                            self._apply_recent_stats(player, recent)
                self._heartbeat = data
                self._heartbeat_at = time.time()
                self._heartbeat_history.append(self._heartbeat_at)
                self._heartbeat_history = self._heartbeat_history[-60:]
                self._status = data.get("state", "Connected")
                self._error = None
                account_puuid = data.get("puuid")
                account_player = (data.get("players") or {}).get(account_puuid)
                if account_player:
                    previous_profile = dict(self._account.get("profile", {}))
                    if previous_profile.get("puuid") != account_puuid:
                        previous_profile = {}
                    same_stats_context = self._stats_context(data) == (
                        account_puuid,
                        self._account.get("matchId"),
                        self._account.get("state"),
                    )
                    if not same_stats_context:
                        previous_profile.pop("recentStats", None)
                    elif previous_profile.get("recentStats"):
                        self._apply_recent_stats(account_player, previous_profile["recentStats"])
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
            elif event_type == "recentStats":
                context = (data.get("accountPuuid"), data.get("matchId"), data.get("state"))
                if context != self._stats_context(self._heartbeat):
                    return
                puuid = data.get("puuid")
                player = (self._heartbeat.get("players") or {}).get(puuid)
                if player is None:
                    return
                self._apply_recent_stats(player, data["stats"])
                if puuid == self._heartbeat.get("puuid"):
                    self._apply_recent_stats(self._account.setdefault("profile", {}), data["stats"])
            elif event_type == "matchLoadout":
                self._loadouts = data
                self._add_event(
                    "data",
                    "Инвентари обновлены",
                    f"Игроков: {len(data.get('Players') or {})}",
                )
            elif event_type == "historyUpdated":
                self._history_revision += 1
            elif event_type == "chat":
                self._chat.append(data)
                self._chat = self._chat[-100:]
            self._touch()

    @staticmethod
    def _stats_context(heartbeat):
        return heartbeat.get("puuid"), heartbeat.get("matchId"), heartbeat.get("state")

    @staticmethod
    def _apply_recent_stats(player, stats):
        player["recentStats"] = copy.deepcopy(stats)
        player["headshotPercentage"] = stats.get("hs", "N/A")
        player["kd"] = stats.get("kd", "N/A")
        if stats.get("requestedMatches") == 1:
            player["earnedRR"] = stats.get("RankedRatingEarned", "N/A")
            player["afkPenalty"] = stats.get("AFKPenalty", "N/A")

    def get_revision(self):
        with self._lock:
            return self._revision

    def snapshot(self):
        with self._lock:
            return {
                "revision": self._revision,
                "history_revision": self._history_revision,
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
