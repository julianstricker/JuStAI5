"""Plugin tests run without network: FakePluginContext routes HTTP to canned answers."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from justai_sdk.manifest import load_manifest
from justai_sdk.plugin import HttpResponse
from justai_sdk.testing import FakePluginContext

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weather_plugin", ROOT / "plugin.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

GEO = '{"results":[{"name":"Bozen","latitude":46.49,"longitude":11.34,"timezone":"Europe/Rome"}]}'
FORECAST = ('{"current":{"temperature_2m":21.4,"weather_code":2,"wind_speed_10m":7.0},'
            '"daily":{"time":["2026-10-14","2026-10-15"],"temperature_2m_max":[23,20],'
            '"temperature_2m_min":[11,9],"weather_code":[0,61]}}')


def routes(fail: bool = False):  # type: ignore[no-untyped-def]
    return {
        "https://geocoding-api.open-meteo.com/*": lambda *a: HttpResponse(status=200, text=GEO),
        "https://api.open-meteo.com/*": lambda *a: HttpResponse(status=503 if fail else 200,
                                                               text="" if fail else FORECAST),
    }


def make(fail: bool = False) -> FakePluginContext:
    ctx = FakePluginContext(load_manifest(ROOT), {"default_location": "Bozen", "language": "de"},
                            http_routes=routes(fail))
    asyncio.run(module.WeatherPlugin(ctx).setup())
    return ctx


def test_manifest_is_valid_and_sandboxed() -> None:
    manifest = load_manifest(ROOT)
    assert manifest.effective_runtime.value == "sandbox"
    assert "network.http" in manifest.permissions


def test_current_weather() -> None:
    ctx = make()
    result = asyncio.run(ctx.call_tool("weather.current", {}))
    assert result.ok and result.data["temperature"] == 21.4
    assert "teilweise bewölkt" in result.message


def test_forecast_and_cache() -> None:
    ctx = make()
    r1 = asyncio.run(ctx.call_tool("weather.forecast", {"location": "Bozen", "days": 2}))
    assert r1.ok and len(r1.data["forecast"]) == 2
    calls = len(ctx.http.requests)
    asyncio.run(ctx.call_tool("weather.forecast", {"location": "Bozen", "days": 2}))
    assert len(ctx.http.requests) == calls  # served from the plugin store


def test_api_failure_is_reported_not_raised() -> None:
    ctx = make(fail=True)
    result = asyncio.run(ctx.call_tool("weather.current", {"location": "Bozen"}))
    assert not result.ok and result.error_code == "weather_unavailable"


def test_hosts_outside_allowlist_are_blocked() -> None:
    ctx = make()
    try:
        asyncio.run(ctx.http.get("https://example.com/"))
    except Exception as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("request to a non-allowlisted host must fail")
