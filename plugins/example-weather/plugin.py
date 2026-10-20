"""Weather plugin (Open-Meteo) - the reference example for plugin authors."""

from __future__ import annotations

import time
from typing import Any

from justai_sdk import DisplayComponentSpec, Plugin, PluginHealth, ToolContext, ToolDefinition, ToolResult
from justai_sdk.plugin import HealthState, PluginError
from pydantic import BaseModel, Field

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> short descriptions
CONDITIONS = {
    0: {"de": "klar", "it": "sereno", "en": "clear"},
    1: {"de": "überwiegend klar", "it": "poco nuvoloso", "en": "mainly clear"},
    2: {"de": "teilweise bewölkt", "it": "parzialmente nuvoloso", "en": "partly cloudy"},
    3: {"de": "bedeckt", "it": "coperto", "en": "overcast"},
    45: {"de": "Nebel", "it": "nebbia", "en": "fog"},
    51: {"de": "leichter Nieselregen", "it": "pioviggine", "en": "light drizzle"},
    61: {"de": "leichter Regen", "it": "pioggia debole", "en": "light rain"},
    63: {"de": "Regen", "it": "pioggia", "en": "rain"},
    65: {"de": "starker Regen", "it": "pioggia forte", "en": "heavy rain"},
    71: {"de": "leichter Schneefall", "it": "neve debole", "en": "light snow"},
    73: {"de": "Schneefall", "it": "neve", "en": "snow"},
    80: {"de": "Regenschauer", "it": "rovesci", "en": "showers"},
    95: {"de": "Gewitter", "it": "temporale", "en": "thunderstorm"},
}
WEEKDAYS = {"de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"], "it": ["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"],
            "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


class LocationParams(BaseModel):
    location: str | None = Field(None, description="Place, e.g. 'Bolzano' or 'Milano'")


class ForecastParams(LocationParams):
    days: int = Field(3, ge=1, le=7)
    show_on_display: bool = Field(False, description="Also show the result on the display in the room")


class WeatherError(PluginError):
    pass


def condition(code: int, lang: str) -> str:
    entry = CONDITIONS.get(code) or CONDITIONS.get(code - code % 10) or {"en": f"code {code}"}
    return entry.get(lang) or entry.get("en", "")


class WeatherPlugin(Plugin):
    """Lifecycle: setup() registers tools and the display component; start()/stop()
    are not needed; health() checks the last API result."""

    async def setup(self) -> None:
        self.last_error: str | None = None
        self.ctx.register_tool(ToolDefinition(
            name="weather.current", description="Current weather at a place.",
            parameters=LocationParams, category="information", timeout_s=15), self.current)
        self.ctx.register_tool(ToolDefinition(
            name="weather.forecast", description="Weather forecast for the next days.",
            parameters=ForecastParams, category="information", timeout_s=20), self.forecast)
        self.ctx.register_display_component(DisplayComponentSpec(
            type="weather-card", description="Weather card",
            props_schema={"type": "object", "required": ["location", "temperature"], "properties": {
                "location": {"type": "string"}, "temperature": {"type": "number"},
                "condition": {"type": "string"}, "forecast": {"type": "array"}}},
            template={"type": "weather", "location": "{{location}}", "temperature": "{{temperature}}",
                      "condition": "{{condition}}", "forecast": "{{forecast}}"}))

    async def health(self) -> PluginHealth:
        if self.last_error:
            return PluginHealth(state=HealthState.DEGRADED, detail=self.last_error)
        return PluginHealth()

    # -------------------------------------------------------------- helpers
    def lang(self, ctx: ToolContext | None = None) -> str:
        """The conversation's language, else the configured one, else English."""
        lang = ((ctx.language if ctx else None) or self.ctx.config.get("language") or "en")[:2]
        return lang if lang in WEEKDAYS else "en"

    async def _cached(self, key: str) -> Any | None:
        minutes = int(self.ctx.config.get("cache_minutes", 15))
        entry = await self.ctx.store.get(key)
        if entry and time.time() - entry["t"] < minutes * 60:
            return entry["v"]
        return None

    async def _geocode(self, name: str, lang: str) -> dict[str, Any]:
        key = f"geo:{name.lower()}"
        cached = await self.ctx.store.get(key)
        if cached:
            return dict(cached)
        r = await self.ctx.http.get(GEO_URL, params={"name": name, "count": 1, "language": lang})
        if r.status != 200:
            raise WeatherError(f"geocoding failed ({r.status})")
        results = r.json().get("results") or []
        if not results:
            raise WeatherError(f"place '{name}' not found")
        place = {k: results[0][k] for k in ("name", "latitude", "longitude", "timezone")}
        await self.ctx.store.put(key, place)
        return place

    async def _forecast(self, place: dict[str, Any], days: int) -> dict[str, Any]:
        key = f"fc:{place['latitude']:.2f},{place['longitude']:.2f}:{days}"
        cached = await self._cached(key)
        if cached:
            return dict(cached)
        r = await self.ctx.http.get(FORECAST_URL, params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code", "forecast_days": days})
        if r.status != 200:
            self.last_error = f"Open-Meteo answered {r.status}"
            raise WeatherError(self.last_error)
        self.last_error = None
        data = r.json()
        await self.ctx.store.put(key, {"t": time.time(), "v": data})
        return dict(data)

    # ---------------------------------------------------------------- tools
    async def current(self, params: LocationParams, ctx: ToolContext) -> ToolResult:
        try:
            place = await self._geocode(params.location or self.ctx.config.get("default_location", "Bozen"),
                                        self.lang(ctx))
            data = await self._forecast(place, 1)
        except WeatherError as exc:
            return ToolResult.failure("weather_unavailable", str(exc))
        cur = data["current"]
        text = condition(int(cur["weather_code"]), self.lang(ctx))
        return ToolResult.success(
            {"location": place["name"], "temperature": cur["temperature_2m"], "condition": text,
             "wind_kmh": cur.get("wind_speed_10m")},
            message=f"{place['name']}: {cur['temperature_2m']:.0f} °C, {text}")

    async def forecast(self, params: ForecastParams, ctx: ToolContext) -> ToolResult:
        try:
            place = await self._geocode(params.location or self.ctx.config.get("default_location", "Bozen"),
                                        self.lang(ctx))
            data = await self._forecast(place, params.days)
        except WeatherError as exc:
            return ToolResult.failure("weather_unavailable", str(exc))
        daily = data["daily"]
        import datetime as dt

        lang = self.lang(ctx)
        days = []
        for i, day in enumerate(daily["time"]):
            weekday = WEEKDAYS[lang][dt.date.fromisoformat(day).weekday()]
            days.append({"day": weekday, "min": daily["temperature_2m_min"][i],
                         "max": daily["temperature_2m_max"][i],
                         "condition": condition(int(daily["weather_code"][i]), lang)})
        result = {"location": place["name"], "temperature": data["current"]["temperature_2m"],
                  "condition": condition(int(data["current"]["weather_code"]), lang), "forecast": days}
        if params.show_on_display and ctx.room_id:
            try:
                await self.ctx.services.show(ctx.room_id, {"title": place["name"], "components": [
                    {"type": "example-weather.weather-card", **result}], "duration_s": 120})
            except Exception as exc:  # display is optional - never fail the forecast
                result["display_error"] = str(exc)
        return ToolResult.success(result, message=f"Forecast for {place['name']}: " + ", ".join(
            f"{d['day']} {d['min']:.0f}–{d['max']:.0f} °C {d['condition']}" for d in days))
