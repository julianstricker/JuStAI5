"""Text helpers for spoken output."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_MARKDOWN = re.compile(r"(\*\*|__|`|#{1,6}\s|^\s*[-*]\s)", re.MULTILINE)


class SentenceSplitter:
    """Collects streamed text and emits complete sentences for TTS."""

    def __init__(self, min_chars: int = 25) -> None:
        self.min_chars = min_chars
        self._buf = ""

    def push(self, text: str) -> list[str]:
        self._buf += text
        parts = _SENTENCE_END.split(self._buf)
        if len(parts) <= 1:
            return []
        complete, self._buf = parts[:-1], parts[-1]
        out: list[str] = []
        pending = ""
        for sentence in complete:
            pending = f"{pending} {sentence}".strip() if pending else sentence.strip()
            if len(pending) >= self.min_chars:
                out.append(pending)
                pending = ""
        if pending:
            self._buf = f"{pending} {self._buf}".strip()
        return [clean_for_speech(s) for s in out if clean_for_speech(s)]

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        cleaned = clean_for_speech(rest)
        return [cleaned] if cleaned else []


def clean_for_speech(text: str) -> str:
    return " ".join(_MARKDOWN.sub("", text).split())
