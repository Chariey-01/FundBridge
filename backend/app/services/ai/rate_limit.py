"""In-process sliding-window rate limiter.

Adequate for a single-process demo deployment. With several workers or
instances each process keeps its own window, so the effective limit is
multiplied; production needs a shared store (for example Redis).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> RateDecision:
        now = self._clock()
        cutoff = now - self.window
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self._max_keys:
                    self._evict(cutoff)
                bucket = self._hits[key] = deque()
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry = max(1, math.ceil(bucket[0] + self.window - now))
                return RateDecision(False, retry)
            bucket.append(now)
            return RateDecision(True, 0)

    def _evict(self, cutoff: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or b[-1] <= cutoff]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:
            # Still full: drop the oldest half rather than grow without bound.
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: self._max_keys // 2]:
                del self._hits[k]
