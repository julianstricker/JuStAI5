"""Brute-force protection for the login (per username and per client address).

After ``free_attempts`` failures within ``window_s`` a key is blocked; the block
doubles with every further failure (capped). A successful login clears the
username key. State is in memory: a restart resets it, which is acceptable for a
single-node home system.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]


@dataclass
class _Entry:
    failures: int = 0
    first_failure: float = 0.0
    blocked_until: float = 0.0


class LoginThrottle:
    def __init__(self, *, free_attempts: int = 5, window_s: float = 900.0, base_block_s: float = 30.0,
                 max_block_s: float = 900.0, clock: Clock = time.monotonic) -> None:
        self.free_attempts = free_attempts
        self.window_s = window_s
        self.base_block_s = base_block_s
        self.max_block_s = max_block_s
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def retry_after(self, *keys: str) -> float:
        """Seconds until a login attempt for these keys is allowed again (0 = allowed)."""
        now = self._clock()
        waits = [e.blocked_until - now for k in keys if (e := self._entries.get(k)) is not None]
        return max([0.0, *waits])

    def failure(self, *keys: str) -> None:
        now = self._clock()
        for key in keys:
            entry = self._entries.get(key)
            if entry is None or now - entry.first_failure > self.window_s:
                entry = self._entries[key] = _Entry(first_failure=now)
            entry.failures += 1
            excess = entry.failures - self.free_attempts
            if excess >= 0:
                entry.blocked_until = now + min(self.max_block_s, self.base_block_s * 2 ** excess)
        if len(self._entries) > 10_000:  # bound memory under a flood of random usernames
            self._entries = {k: e for k, e in self._entries.items() if now - e.first_failure <= self.window_s}

    def success(self, key: str) -> None:
        self._entries.pop(key, None)
