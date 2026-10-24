import copy
import threading
import time

from src.player_stats import PlayerStats


class HistorySync:
    """Retry delayed match results independently of the monitor's WebSocket wait."""

    MAX_ATTEMPTS = 8
    RETRY_DELAYS = (15, 30, 60, 120, 240, 300, 300, 300)

    def __init__(self, stats, client, config, state_store, log):
        self.stats = stats
        self.client = client
        self.state_store = state_store
        self.log = log
        self.player_stats = PlayerStats(None, log, config)
        self._worker_client = None
        self._source_auth = None
        self._process_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._active_match = None
        self._jobs = {}
        self._attempts = {}
        self._thread = None

    def start(self):
        if self._thread is None and not self._stop.is_set():
            self._thread = threading.Thread(target=self._run, name="history-sync", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def set_active_match(self, match_id):
        with self._lock:
            self._active_match = match_id or None
        self._wake.set()

    def notify(self):
        self._wake.set()

    def _refresh_client(self):
        source = (dict(self.client.headers), dict(self.client.lockfile))
        if self._worker_client is None or source != self._source_auth:
            client = copy.copy(self.client)
            client.headers, client.lockfile = map(dict, source)
            self._worker_client = client
            self._source_auth = source
        self.player_stats.Requests = self._worker_client

    def process_once(self, now=None):
        with self._process_lock:
            return self._process_once(now)

    def _process_once(self, now):
        if self._stop.is_set():
            return False
        now = time.monotonic() if now is None else now
        incomplete = self.stats.get_incomplete_matches(30)
        with self._lock:
            for match_id in list(self._jobs):
                if match_id not in incomplete:
                    del self._jobs[match_id]
            for match_id in incomplete:
                if self._attempts.get(match_id, 0) < self.MAX_ATTEMPTS:
                    self._jobs.setdefault(match_id, now)
            candidate = next((match_id for match_id, due in self._jobs.items()
                              if match_id != self._active_match and due <= now), None)
            if candidate is None:
                return False
            attempt = self._attempts.get(candidate, 0)
            self._attempts[candidate] = attempt + 1
            self._jobs[candidate] = now + self.RETRY_DELAYS[attempt]

        self._refresh_client()
        availability, players = self.player_stats.get_match_stats(candidate)
        with self._lock:
            if self._stop.is_set() or candidate == self._active_match:
                return True
        if availability == "ready":
            # A clear or another writer may have resolved this job during the fetch.
            current = self.stats.get_incomplete_matches(30)
            if candidate in current:
                if self.stats.update_match_stats(candidate, players):
                    self.state_store.publish("historyUpdated", {})
                current = self.stats.get_incomplete_matches(30)
            if candidate not in current:
                with self._lock:
                    self._jobs.pop(candidate, None)
            else:
                self.player_stats.invalidate_match(candidate)
        if self._attempts[candidate] >= self.MAX_ATTEMPTS:
            with self._lock:
                self._jobs.pop(candidate, None)
        return True

    def _run(self):
        # Let startup identify the active match before any history backfill.
        self._stop.wait(3)
        while not self._stop.is_set():
            try:
                attempted = self.process_once()
            except Exception as exc:
                self.log(f"History synchronization deferred ({type(exc).__name__})")
                attempted = False
            self._wake.wait(2 if attempted else 15)
            self._wake.clear()
