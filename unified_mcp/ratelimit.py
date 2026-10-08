"""Per-(subject, tool) token-bucket rate limiter."""
from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_s: float, clock: Callable[[], float] = time.monotonic):
        self.capacity, self.refill, self.clock = capacity, refill_per_s, clock
        self._state: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, subject: str, tool: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        key, now = (subject, tool), self.clock()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                return True, 0.0
            self._state[key] = (tokens, now)
            return False, (1 - tokens) / self.refill
