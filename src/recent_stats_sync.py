import copy
import threading
import time
from collections import OrderedDict, deque

from src.player_stats import PlayerStats


class RecentStatsSync:
    """Resolve recent averages on one worker, without touching match history."""

    MAX_ATTEMPTS = 3
    RETRY_DELAYS = (30, 60)
    STEP_DELAY = 0.35
    MATCH_LIMIT = 1
    CACHE_MAX_SIZE = 128
    CACHE_TTL = 300

    def __init__(self, client, config, state_store, log):
        self.client = client
        self.config = config
        self.state_store = state_store
        self.log = log
        self.player_stats = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._thread = None
        self._context = None
        self._generation = 0
        self._worker_generation = -1
        self._jobs = deque()
        self._next_step = 0
        self._cache_generation = 0
        self._worker_cache_generation = -1
        self._ready_cache = OrderedDict()
        self._detail_times = OrderedDict()
        self._worker_client = None
        self._source_auth = None
        self._auth_account = None
        self._auth_generation = 0
        self._worker_auth_generation = -1

    def start(self):
        with self._lock:
            if self._thread is None and not self._stop.is_set():
                self._thread = threading.Thread(
                    target=self._run, name="recent-stats-sync", daemon=True
                )
                self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def submit(self, heartbeat):
        account = heartbeat.get("puuid")
        roster = tuple(sorted(puuid for puuid in (heartbeat.get("players") or {}) if puuid))
        context = (account, heartbeat.get("matchId"), heartbeat.get("state"), roster)
        with self._lock:
            if self._stop.is_set() or context == self._context:
                return
            previous = self._context
            reusable = (
                previous is not None and account and context[1]
                and previous[:2] == context[:2]
                and previous[2] in ("PREGAME", "INGAME")
                and context[2] in ("PREGAME", "INGAME")
            )
            if not reusable:
                self._cache_generation += 1
            if (previous is None or previous[0] != account or not account
                    or context[2] == "DISCONNECTED"):
                self._auth_generation += 1
            self._context = context
            self._generation += 1
        self._wake.set()

    def _cancelled(self, generation):
        with self._lock:
            return self._stop.is_set() or generation != self._generation

    def _refresh_client(self, account):
        source = (dict(self.client.headers), dict(self.client.lockfile))
        if (self._worker_client is None or source != self._source_auth
                or account != self._auth_account):
            client = copy.copy(self.client)
            client.headers, client.lockfile = map(dict, source)
            self._worker_client = client
            self._source_auth = source
            self._auth_account = account
        if self.player_stats is not None:
            self.player_stats.Requests = self._worker_client
        return self._worker_client

    def _prune_cache(self, now):
        for puuid, (created, _) in list(self._ready_cache.items()):
            if now - created >= self.CACHE_TTL:
                del self._ready_cache[puuid]
        while len(self._ready_cache) > self.CACHE_MAX_SIZE:
            self._ready_cache.popitem(last=False)
        if self.player_stats is None:
            self._detail_times.clear()
            return
        cache = self.player_stats.match_details_cache
        for match_id in list(self._detail_times):
            if match_id not in cache:
                del self._detail_times[match_id]
        for match_id in cache:
            self._detail_times.setdefault(match_id, now)
        for match_id, created in list(self._detail_times.items()):
            if now - created >= self.CACHE_TTL:
                cache.pop(match_id, None)
                del self._detail_times[match_id]
        while len(self._detail_times) > self.CACHE_MAX_SIZE:
            match_id, _ = self._detail_times.popitem(last=False)
            cache.pop(match_id, None)

    @staticmethod
    def _close(job):
        iterator = job.get("iterator")
        if iterator is not None:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
            job["iterator"] = None

    def _reset(self, generation, context, cache_generation, auth_generation, now):
        for job in self._jobs:
            self._close(job)
        self._jobs.clear()
        if auth_generation != self._worker_auth_generation:
            self._worker_client = None
            self._source_auth = None
        self._worker_auth_generation = auth_generation
        if cache_generation != self._worker_cache_generation:
            self.player_stats = None
            self._ready_cache.clear()
            self._detail_times.clear()
        self._worker_cache_generation = cache_generation
        self._worker_generation = generation
        if context is None or not context[0] or context[2] == "DISCONNECTED":
            self.player_stats = None
            self._worker_client = None
            self._source_auth = None
            return
        account, _, _, roster = context
        ordered = ([account] if account in roster else []) + [p for p in roster if p != account]
        if not ordered:
            self.player_stats = None
        elif self.player_stats is None:
            self.player_stats = PlayerStats(self._refresh_client(account), self.log, self.config)
        self._prune_cache(now)
        for puuid in ordered:
            self._jobs.append({
                "puuid": puuid, "attempts": 0, "due": 0,
                "iterator": None, "last": None,
            })

    def _unavailable(self, job):
        result = dict(job["last"] or {})
        result.setdefault("matches", 0)
        result.setdefault("requestedMatches", self.MATCH_LIMIT)
        result.setdefault("availableMatches", 0)
        for key in ("hs", "kd", "kills", "deaths", "assists", "adr"):
            result.setdefault(key, "N/A")
        result["status"] = "partial" if result["matches"] else "unavailable"
        return result

    def process_once(self, now=None):
        """Advance at most one player's iterator; explicit time supports offline tests."""
        with self._process_lock:
            return self._process_once(now)

    def _process_once(self, now):
        explicit_time = now is not None
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._stop.is_set():
                return False
            generation, context = self._generation, self._context
            cache_generation = self._cache_generation
            auth_generation = self._auth_generation
        if generation != self._worker_generation:
            self._reset(generation, context, cache_generation, auth_generation, now)
        if self._cancelled(generation) or now < self._next_step:
            return False
        job = None
        for _ in range(len(self._jobs)):
            candidate = self._jobs.popleft()
            if candidate["due"] <= now:
                job = candidate
                break
            self._jobs.append(candidate)
        if job is None:
            return False

        self._prune_cache(now)
        cached = self._ready_cache.get(job["puuid"])
        try:
            if cached is not None:
                result = dict(cached[1])
            else:
                if job["iterator"] is None:
                    job["attempts"] += 1
                    self._refresh_client(context[0])
                    job["iterator"] = iter(self.player_stats.iter_recent_stats(
                        job["puuid"], limit=self.MATCH_LIMIT,
                        exclude_match_id=context[1],
                        should_stop=lambda: self._cancelled(generation),
                    ))
                result = dict(next(job["iterator"]))
            if result.get("status") not in ("loading", "ready", "partial", "unavailable", "empty"):
                result = self._unavailable(job)
        except StopIteration:
            result = self._unavailable(job)
        except Exception as exc:
            self.log(f"Recent statistics unavailable ({type(exc).__name__}); will retry")
            result = self._unavailable(job)
        previous = job["last"] or {}
        if result.get("matches", 0) < previous.get("matches", 0) and result["status"] != "ready":
            result = previous | {"status": "loading" if result["status"] == "loading" else "partial"}
        finished_at = now if explicit_time else time.monotonic()
        self._next_step = finished_at + self.STEP_DELAY

        # Keep the generation check and publication atomic relative to submit().
        with self._lock:
            if self._cancelled(generation):
                self._close(job)
                return True
            if (cached is None and result.get("status") == "ready"
                    and result.get("matches") == self.MATCH_LIMIT
                    and result.get("requestedMatches") == self.MATCH_LIMIT):
                self._ready_cache[job["puuid"]] = (finished_at, dict(result))
            self._prune_cache(finished_at)
            self.state_store.publish("recentStats", {
                "accountPuuid": context[0], "matchId": context[1],
                "state": context[2], "puuid": job["puuid"], "stats": result,
            })
        job["last"] = result
        status = result["status"]
        if status == "loading":
            self._jobs.append(job)
        else:
            self._close(job)
            if status in ("partial", "unavailable") and job["attempts"] < self.MAX_ATTEMPTS:
                job["due"] = finished_at + self.RETRY_DELAYS[job["attempts"] - 1]
                self._jobs.append(job)
        return True

    def _wait_delay(self):
        if self._worker_generation != self._generation:
            return 0
        if not self._jobs:
            return None
        due = max(self._next_step, min(job["due"] for job in self._jobs))
        return max(0, due - time.monotonic())

    def _run(self):
        try:
            while not self._stop.is_set():
                self._wake.clear()
                try:
                    self.process_once()
                    delay = self._wait_delay()
                except Exception as exc:
                    self.log(f"Recent statistics synchronization deferred ({type(exc).__name__})")
                    delay = 1
                self._wake.wait(delay)
        finally:
            for job in self._jobs:
                self._close(job)
            self._jobs.clear()
            self.player_stats = None
