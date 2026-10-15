"""Room-aware wakeword arbitration.

Several microphones may hear the same wakeword. Candidates from endpoints of the
same *arbitration group* that arrive within a short window are collected, scored,
and exactly one endpoint wins. A reliable choice is preferred over the fastest
activation (requirement 5.7), so the decision waits for the window to close.

Score = wakeword confidence + loudness/SNR + VAD + configured priority. An endpoint
that already has an active session wins outright (the user is talking there).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from justai.audio.processor import WakeCandidate


@dataclass(frozen=True)
class ArbitrationContext:
    group: str
    priority: int
    has_active_session: bool


@dataclass
class ArbitrationResult:
    winner: WakeCandidate
    losers: list[WakeCandidate] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


ContextLookup = Callable[[str], ArbitrationContext | None]
ResultHandler = Callable[[ArbitrationResult], Awaitable[None]]
RejectHandler = Callable[[WakeCandidate, str], Awaitable[None]]


def score(c: WakeCandidate, ctx: ArbitrationContext) -> float:
    s = c.score * 10.0  # 0..10
    s += max(-10.0, min(c.snr_db, 40.0)) * 0.15  # up to +6 for a clear signal
    s += c.vad * 2.0
    s += ctx.priority * 1.0
    if c.during_playback:
        s -= 3.0
    if ctx.has_active_session:
        s += 100.0
    return s


class WakeArbiter:
    def __init__(self, lookup: ContextLookup, handler: ResultHandler, window_s: float = 0.8,
                 suppress_s: float = 2.0, on_reject: RejectHandler | None = None) -> None:
        self.lookup = lookup
        self.handler = handler
        self.window_s = window_s
        # Microphones behind different network paths hear the same utterance with
        # different delays: late duplicates of an already decided wakeword are dropped.
        self.suppress_s = suppress_s
        self.on_reject = on_reject
        self._pending: dict[str, list[WakeCandidate]] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._decided: dict[str, tuple[float, str]] = {}  # group -> (time, winning endpoint)
        self._background: set[asyncio.Task[None]] = set()
        self.decisions = 0

    def submit(self, candidate: WakeCandidate) -> None:
        ctx = self.lookup(candidate.endpoint_id)
        if ctx is None:
            return
        group = ctx.group
        decided = self._decided.get(group)
        if decided is not None and candidate.endpoint_id != decided[1] \
                and abs(candidate.t - decided[0]) < self.suppress_s:
            if self.on_reject is not None:
                task: asyncio.Task[None] = asyncio.ensure_future(
                    self.on_reject(candidate, "late duplicate of an accepted wakeword"))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
            return
        bucket = self._pending.setdefault(group, [])
        # One candidate per endpoint and window (keep the best).
        existing = next((c for c in bucket if c.endpoint_id == candidate.endpoint_id), None)
        if existing is not None:
            if candidate.score > existing.score:
                bucket[bucket.index(existing)] = candidate
            return
        bucket.append(candidate)
        if group not in self._timers:
            self._timers[group] = asyncio.create_task(self._close_window(group))

    async def _close_window(self, group: str) -> None:
        try:
            await asyncio.sleep(self.window_s)
        finally:
            self._timers.pop(group, None)
        candidates = self._pending.pop(group, [])
        if not candidates:
            return
        result = self.decide(candidates)
        if result is not None:
            self.decisions += 1
            self._decided[group] = (result.winner.t, result.winner.endpoint_id)
            await self.handler(result)

    def decide(self, candidates: list[WakeCandidate]) -> ArbitrationResult | None:
        scored: list[tuple[float, WakeCandidate]] = []
        for c in candidates:
            ctx = self.lookup(c.endpoint_id)
            if ctx is not None:
                scored.append((score(c, ctx), c))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], x[1].t))
        return ArbitrationResult(
            winner=scored[0][1],
            losers=[c for _, c in scored[1:]],
            scores={c.endpoint_id: round(s, 2) for s, c in scored},
        )
