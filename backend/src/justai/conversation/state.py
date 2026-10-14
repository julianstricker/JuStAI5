"""Conversation state machine.

    IDLE -> STARTING -> LISTENING <-> PROCESSING <-> SPEAKING -> ... -> ENDED

The inactivity timeout only runs in LISTENING (never while the assistant is
thinking or speaking) and starts counting when the user can actually be heard
again, i.e. after the echo window of the last answer has closed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ENDED = "ended"


ALLOWED: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE: {SessionState.STARTING, SessionState.ENDED},
    SessionState.STARTING: {SessionState.LISTENING, SessionState.PROCESSING, SessionState.SPEAKING,
                            SessionState.ENDED},
    SessionState.LISTENING: {SessionState.PROCESSING, SessionState.SPEAKING, SessionState.ENDED},
    SessionState.PROCESSING: {SessionState.SPEAKING, SessionState.LISTENING, SessionState.ENDED},
    SessionState.SPEAKING: {SessionState.LISTENING, SessionState.PROCESSING, SessionState.ENDED},
    SessionState.ENDED: set(),
}


class InvalidTransition(Exception):  # noqa: N818
    pass


Listener = Callable[[SessionState, SessionState, str], None]
Clock = Callable[[], float]


class StateMachine:
    def __init__(self, inactivity_timeout_s: float, clock: Clock = time.monotonic) -> None:
        self.state = SessionState.IDLE
        self.inactivity_timeout_s = inactivity_timeout_s
        self._clock = clock
        self._listeners: list[Listener] = []
        self._last_activity = clock()
        self.history: list[tuple[float, SessionState, str]] = []

    def on_change(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def can(self, target: SessionState) -> bool:
        return target in ALLOWED[self.state] or target == self.state

    def transition(self, target: SessionState, reason: str = "") -> bool:
        """Move to ``target``. Returns False if already there; raises on invalid moves."""
        if target == self.state:
            return False
        if target not in ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state} -> {target} ({reason})")
        previous = self.state
        self.state = target
        now = self._clock()
        if target == SessionState.LISTENING:
            self._last_activity = max(self._last_activity, now)
        self.history.append((now, target, reason))
        for listener in self._listeners:
            listener(previous, target, reason)
        return True

    def try_transition(self, target: SessionState, reason: str = "") -> bool:
        if not self.can(target):
            return False
        return self.transition(target, reason)

    # ------------------------------------------------------------ inactivity
    def activity(self, at: float | None = None) -> None:
        """User activity (speech) or an extended echo window postpones the timeout."""
        t = self._clock() if at is None else at
        self._last_activity = max(self._last_activity, t)

    def inactive_for(self) -> float:
        return self._clock() - self._last_activity

    def timed_out(self) -> bool:
        return (self.state == SessionState.LISTENING
                and self.inactive_for() >= self.inactivity_timeout_s)

    @property
    def ended(self) -> bool:
        return self.state == SessionState.ENDED
