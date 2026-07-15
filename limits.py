"""
Abuse/cost guardrails for the ENEA backend (in-memory, single-process).

- TTLCache: caches results by input so repeated identical requests (everyone
  tries "GitHub Copilot") don't hit the paid API. Web search is the costly part,
  so caching the evidence phase saves the most.
- RateLimiter: fixed-window per-key (per-IP) limit against loops.
- DailyBudget: hard cap on the number of billable (cache-miss) runs per UTC day,
  so the daily spend is bounded regardless of how many IPs call.

NOTE: state is per-process. Run the server with a single worker (the default).
For multi-worker/multi-instance deployments, back these with Redis instead.
Injectable `now` keeps the logic unit-testable without real time.
"""

import datetime
import hashlib
import threading
import time


def cache_key(*parts):
    return hashlib.sha256("\x1f".join(p.lower() for p in parts).encode("utf-8")).hexdigest()


class TTLCache:
    def __init__(self, ttl=86400, maxsize=500):
        self.ttl = ttl
        self.maxsize = maxsize
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            item = self._d.get(key)
            if not item:
                return None
            exp, val = item
            if exp < now:
                self._d.pop(key, None)
                return None
            return val

    def set(self, key, val, now=None):
        now = time.time() if now is None else now
        with self._lock:
            if len(self._d) >= self.maxsize:
                for k in [k for k, (exp, _) in self._d.items() if exp < now]:
                    self._d.pop(k, None)
                if len(self._d) >= self.maxsize:
                    self._d.pop(next(iter(self._d)), None)  # evict oldest inserted
            self._d[key] = (now + self.ttl, val)


class RateLimiter:
    """Fixed sliding window: at most `limit` events per `window` seconds per key."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if t > now - self.window]
            if len(bucket) >= self.limit:
                self._hits[key] = bucket
                retry_after = int(self.window - (now - min(bucket))) + 1
                return False, retry_after
            bucket.append(now)
            self._hits[key] = bucket
            # opportunistic cleanup
            if len(self._hits) > 10000:
                for k in [k for k, v in self._hits.items() if not any(t > now - self.window for t in v)]:
                    self._hits.pop(k, None)
            return True, 0


class DailyBudget:
    """Hard cap on billable runs per UTC day."""

    def __init__(self, limit):
        self.limit = limit
        self._day = None
        self._count = 0
        self._lock = threading.Lock()

    @staticmethod
    def _today(now):
        return datetime.datetime.utcfromtimestamp(now).date().isoformat()

    def check_and_inc(self, now=None):
        """Return True and increment if under the cap; False if the cap is reached."""
        now = time.time() if now is None else now
        with self._lock:
            day = self._today(now)
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    def remaining(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            if self._today(now) != self._day:
                return self.limit
            return max(0, self.limit - self._count)
