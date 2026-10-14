"""AI usage and cost accounting (aggregated per day/provider/model/role)."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from justai.db.engine import Database
from justai.db.models import AIUsage

# Rough USD prices per 1M tokens (input, output) for cost limits. Unknown models
# count as 0 - limits are a safety net, not billing.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.30, 2.50),
    "gemini-3.8-live": (1.00, 4.00),
    "gemini-3.5-flash": (0.30, 2.50),
    "gpt-realtime": (4.00, 16.00),
}


@dataclass
class _Agg:
    requests: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    cost_usd: float = 0.0
    latency_ms_total: int = 0


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return 0.0
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


class UsageTracker:
    def __init__(self, db: Database | None) -> None:
        self.db = db
        self._pending: dict[tuple[datetime, str, str, str], _Agg] = defaultdict(_Agg)
        self._today_cost = 0.0
        self._today: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._load_today()
        self._task = asyncio.create_task(self._flush_loop(), name="ai-usage-flush")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()

    @staticmethod
    def _day() -> datetime:
        now = datetime.now(UTC)
        return datetime(now.year, now.month, now.day, tzinfo=UTC)

    async def _load_today(self) -> None:
        self._today = self._day()
        if self.db is None:
            return
        async with self.db.session() as s:
            total = await s.scalar(select(func.coalesce(func.sum(AIUsage.cost_usd), 0.0))
                                   .where(AIUsage.day == self._today))
        self._today_cost = float(total or 0.0)

    def record(self, *, provider: str, model: str, role: str, ok: bool, input_tokens: int = 0,
               output_tokens: int = 0, audio_seconds: float = 0.0, latency_ms: int = 0,
               cost_usd: float | None = None) -> None:
        day = self._day()
        if self._today != day:
            self._today, self._today_cost = day, 0.0
        cost = cost_usd if cost_usd is not None else estimate_cost(model, input_tokens, output_tokens)
        agg = self._pending[(day, provider, model, role)]
        agg.requests += 1
        agg.failures += 0 if ok else 1
        agg.input_tokens += input_tokens
        agg.output_tokens += output_tokens
        agg.audio_seconds += audio_seconds
        agg.cost_usd += cost
        agg.latency_ms_total += latency_ms
        self._today_cost += cost

    @property
    def today_cost_usd(self) -> float:
        return self._today_cost

    async def flush(self) -> None:
        if self.db is None or not self._pending:
            return
        pending, self._pending = self._pending, defaultdict(_Agg)
        async with self.db.session() as s:
            for (day, provider, model, role), a in pending.items():
                stmt = insert(AIUsage).values(day=day, provider=provider, model=model, role=role,
                                              requests=a.requests, failures=a.failures,
                                              input_tokens=a.input_tokens,
                                              output_tokens=a.output_tokens,
                                              audio_seconds=a.audio_seconds, cost_usd=a.cost_usd,
                                              latency_ms_total=a.latency_ms_total)
                excluded = stmt.excluded
                await s.execute(stmt.on_conflict_do_update(
                    index_elements=[AIUsage.day, AIUsage.provider, AIUsage.model, AIUsage.role],
                    set_={
                        "requests": AIUsage.requests + excluded.requests,
                        "failures": AIUsage.failures + excluded.failures,
                        "input_tokens": AIUsage.input_tokens + excluded.input_tokens,
                        "output_tokens": AIUsage.output_tokens + excluded.output_tokens,
                        "audio_seconds": AIUsage.audio_seconds + excluded.audio_seconds,
                        "cost_usd": AIUsage.cost_usd + excluded.cost_usd,
                        "latency_ms_total": AIUsage.latency_ms_total + excluded.latency_ms_total,
                    }))

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            with contextlib.suppress(Exception):
                await self.flush()

    async def summary(self, days: int = 30) -> list[AIUsage]:
        if self.db is None:
            return []
        await self.flush()
        async with self.db.session() as s:
            rows = await s.scalars(select(AIUsage).order_by(AIUsage.day.desc()).limit(days * 20))
            return list(rows.all())
