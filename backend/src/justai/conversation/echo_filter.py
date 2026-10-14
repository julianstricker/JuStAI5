"""Last line of defence against self-conversation.

If a user transcript closely matches something the assistant said moments ago,
it is treated as echo and discarded - independently of any LLM instructions.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from difflib import SequenceMatcher


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", text)


class EchoTranscriptFilter:
    def __init__(self, window_s: float = 25.0, threshold: float = 0.6, min_words: int = 2,
                 clock: object = time.monotonic) -> None:
        self.window_s = window_s
        self.threshold = threshold
        self.min_words = min_words
        self._clock = clock
        self._said: deque[tuple[float, list[str]]] = deque(maxlen=50)

    def assistant_said(self, text: str) -> None:
        words = normalize(text)
        if words:
            self._said.append((self._now(), words))

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def similarity(self, user_text: str) -> float:
        words = normalize(user_text)
        if len(words) < self.min_words:
            return 0.0
        cutoff = self._now() - self.window_s
        best = 0.0
        for t, said in self._said:
            if t < cutoff:
                continue
            # Fraction of the user words that occur in order within the assistant text.
            matcher = SequenceMatcher(a=said, b=words, autojunk=False)
            matched = sum(block.size for block in matcher.get_matching_blocks())
            best = max(best, matched / len(words))
        return best

    def is_echo(self, user_text: str) -> bool:
        return self.similarity(user_text) >= self.threshold
