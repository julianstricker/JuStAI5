"""Minimal 5-field cron expressions (minute hour day-of-month month day-of-week)."""

from __future__ import annotations

from datetime import datetime

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError("cron step must be positive")
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron value out of range: {part}")
        values.update(range(start, end + 1, step))
    return values


class CronExpr:
    def __init__(self, expr: str) -> None:
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError("cron expression needs 5 fields")
        fields[4] = fields[4].replace("7", "0")
        self.minute, self.hour, self.dom, self.month, self.dow = (
            _parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES, strict=True))
        self._dom_any = fields[2] == "*"
        self._dow_any = fields[4] == "*"

    def matches(self, t: datetime) -> bool:
        if t.minute not in self.minute or t.hour not in self.hour or t.month not in self.month:
            return False
        dow = (t.weekday() + 1) % 7  # Python Monday=0 -> cron Sunday=0
        dom_ok, dow_ok = t.day in self.dom, dow in self.dow
        if self._dom_any or self._dow_any:  # standard cron: OR when both are restricted
            return dom_ok and dow_ok
        return dom_ok or dow_ok
