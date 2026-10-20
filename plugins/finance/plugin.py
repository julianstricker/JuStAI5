"""Market quotes and charts (Yahoo Finance chart endpoint, unofficial)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from justai_sdk import Plugin, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (JuStAI5 home assistant)"}
PERIODS = {"1d": ("1d", "5m"), "5d": ("5d", "30m"), "1mo": ("1mo", "1d"), "6mo": ("6mo", "1d"),
           "1y": ("1y", "1wk"), "5y": ("5y", "1mo")}


class QuotesParams(BaseModel):
    symbols: list[str] = Field(default_factory=list, max_length=12,
                               description="Tickers like AAPL, MSFT, ^GDAXI, BTC-EUR; empty = overview")


class ChartParams(BaseModel):
    symbol: str
    period: str = Field("1d", description="1d, 5d, 1mo, 6mo, 1y, 5y")


class FinancePlugin(Plugin):
    async def setup(self) -> None:
        self.ctx.register_tool(ToolDefinition(
            name="finance.quotes",
            description="Current prices (stocks, indices, currencies, crypto). The result suits "
                        "display.show with stock-quote components.",
            parameters=QuotesParams, category="information", timeout_s=20), self.quotes)
        self.ctx.register_tool(ToolDefinition(
            name="finance.chart", description="Price history of a symbol (for chart components).",
            parameters=ChartParams, category="information", timeout_s=20), self.chart)

    async def _fetch(self, symbol: str, range_: str, interval: str) -> dict[str, Any]:
        r = await self.ctx.http.get(URL.format(symbol=symbol), params={"range": range_, "interval": interval},
                                    headers=HEADERS)
        if r.status != 200:
            raise ValueError(f"{symbol}: HTTP {r.status}")
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            raise ValueError(f"{symbol}: no data")
        return dict(result[0])

    async def quotes(self, params: QuotesParams, ctx: ToolContext) -> ToolResult:
        symbols = params.symbols or list(self.ctx.config.get("default_symbols") or [])
        out, errors = [], []
        for symbol in symbols:
            try:
                meta = (await self._fetch(symbol, "1d", "1d"))["meta"]
            except Exception as exc:
                errors.append(str(exc))
                continue
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            change = price - prev if price is not None and prev else None
            out.append({"symbol": meta.get("symbol", symbol), "name": meta.get("shortName") or meta.get("longName"),
                        "price": price, "currency": meta.get("currency", ""),
                        "change": round(change, 4) if change is not None else None,
                        "change_pct": round(change / prev * 100, 2) if change is not None else None,
                        "time": datetime.fromtimestamp(meta.get("regularMarketTime", 0), UTC)
                        .isoformat(timespec="minutes")})
        if not out:
            return ToolResult.failure("no_data", "; ".join(errors) or "no prices")
        return ToolResult.success({"quotes": out, "errors": errors, "source": "Yahoo Finance (unofficial)"},
                                  message=", ".join(f"{q['symbol']} {q['price']} {q['currency']}" for q in out))

    async def chart(self, params: ChartParams, ctx: ToolContext) -> ToolResult:
        range_, interval = PERIODS.get(params.period, PERIODS["1d"])
        try:
            data = await self._fetch(params.symbol, range_, interval)
        except Exception as exc:
            return ToolResult.failure("no_data", str(exc))
        times = data.get("timestamp") or []
        closes = ((data.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        points = [[datetime.fromtimestamp(t, UTC).isoformat(timespec="minutes"), round(c, 4)]
                  for t, c in zip(times, closes, strict=False) if c is not None]
        return ToolResult.success({"symbol": params.symbol, "period": params.period, "points": points[-400:],
                                   "chart_component": {"type": "chart", "kind": "line", "x_type": "time",
                                                       "title": f"{params.symbol} ({params.period})",
                                                       "series": [{"name": params.symbol, "points": points[-400:]}]}},
                                  message=f"{len(points)} Kurspunkte")
