"""Display render schema.

A presentation document is a tree of *typed components*. Display clients render
only builtin component types with their own trusted implementations; plugin
components are templates that the core expands into builtin components. No HTML
or script from an LLM or plugin ever reaches a display.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import jsonschema
from justai_sdk.plugin import DisplayComponentSpec
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from justai.common.errors import ValidationFailed

MAX_DEPTH = 6
MAX_COMPONENTS = 200
_URL_RE = re.compile(r"^(https://|/api/media/|data:image/(png|jpeg|webp|gif);base64,)")


class _C(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Text(_C):
    text: str = Field(max_length=4000)
    size: Literal["s", "m", "l", "xl"] = "m"
    align: Literal["left", "center", "right"] = "left"


class Heading(_C):
    text: str = Field(max_length=300)
    level: int = Field(1, ge=1, le=3)


class Markdown(_C):
    markdown: str = Field(max_length=20000)  # rendered without raw HTML by the client


class Image(_C):
    src: str
    alt: str = ""
    fit: Literal["contain", "cover"] = "contain"

    @field_validator("src")
    @classmethod
    def _safe_src(cls, v: str) -> str:
        if not _URL_RE.match(v):
            raise ValueError("image src must be https, /api/media/ or a data:image URL")
        return v


class Table(_C):
    columns: list[str] = Field(max_length=20)
    rows: list[list[str | int | float | None]] = Field(max_length=500)
    caption: str | None = None


class KVItem(_C):
    label: str
    value: str | int | float


class KeyValue(_C):
    items: list[KVItem] = Field(max_length=50)


class Stat(_C):
    label: str
    value: str | int | float
    unit: str | None = None
    delta: str | None = None
    trend: Literal["up", "down", "flat"] | None = None


class Series(_C):
    name: str
    points: list[tuple[str | int | float, float]] = Field(max_length=5000)


class Chart(_C):
    kind: Literal["line", "bar", "area"] = "line"
    title: str | None = None
    x_type: Literal["time", "category", "number"] = "category"
    unit: str | None = None
    series: list[Series] = Field(max_length=10)


class ListC(_C):
    items: list[str] = Field(max_length=100)
    ordered: bool = False


class Forecast(_C):
    day: str
    min: float | None = None
    max: float | None = None
    condition: str = ""


class Weather(_C):
    location: str
    temperature: float | None = None
    condition: str = ""
    unit: str = "°C"
    forecast: list[Forecast] = Field(default_factory=list, max_length=14)


class StockQuote(_C):
    symbol: str
    name: str | None = None
    price: float
    currency: str = "USD"
    change: float | None = None
    change_pct: float | None = None
    time: str | None = None


class Camera(_C):
    device_id: str


class Notification(_C):
    title: str
    message: str = ""
    level: Literal["info", "success", "warning", "error"] = "info"


class ChoiceOption(_C):
    id: str = Field(max_length=64)
    label: str = Field(max_length=200)


class Choice(_C):
    prompt: str
    options: list[ChoiceOption] = Field(min_length=1, max_length=12)


class Button(_C):
    label: str
    action_id: str = Field(max_length=64)


class Clock(_C):
    show_date: bool = True


class Container(_C):
    children: list[dict[str, Any]] = Field(max_length=50)
    title: str | None = None
    columns: int = Field(2, ge=1, le=6)


BUILTIN: dict[str, type[BaseModel]] = {
    "text": Text,
    "heading": Heading,
    "markdown": Markdown,
    "image": Image,
    "table": Table,
    "kv": KeyValue,
    "stat": Stat,
    "chart": Chart,
    "list": ListC,
    "weather": Weather,
    "stock-quote": StockQuote,
    "camera": Camera,
    "notification": Notification,
    "choice": Choice,
    "button": Button,
    "clock": Clock,
    "card": Container,
    "row": Container,
    "grid": Container,
}
CONTAINERS = {"card", "row", "grid"}
INTERACTIVE = {"choice", "button"}

# Capability a display needs to render a component type.
REQUIRED_CAPABILITY = {
    "camera": "display.video",
    "choice": "display.interactive",
    "button": "display.interactive",
    "chart": "display.dashboard",
    "grid": "display.dashboard",
}


class PresentationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=200)
    layout: Literal["single", "dashboard", "fullscreen"] = "single"
    theme: Literal["auto", "dark", "light"] = "auto"
    components: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    duration_s: int | None = Field(None, ge=3, le=24 * 3600)


class ComponentRegistry:
    """Builtin components plus plugin template components."""

    def __init__(self) -> None:
        self._plugin: dict[str, tuple[DisplayComponentSpec, str]] = {}

    def register(self, spec: DisplayComponentSpec, owner: str) -> None:
        if spec.type in BUILTIN:
            raise ValueError(f"component type {spec.type} is builtin")
        jsonschema.Draft202012Validator.check_schema(spec.props_schema)
        self._plugin[spec.type] = (spec, owner)

    def unregister_owner(self, owner: str) -> None:
        for key in [k for k, (_, o) in self._plugin.items() if o == owner]:
            del self._plugin[key]

    def catalog(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {"type": t, "builtin": True, "props_schema": m.model_json_schema()}
            for t, m in BUILTIN.items()
        ]
        out += [
            {"type": t, "builtin": False, "owner": o, "description": s.description,
             "props_schema": s.props_schema}
            for t, (s, o) in self._plugin.items()
        ]
        return out

    # ---------------------------------------------------------------- validation
    def normalize(self, document: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
        """Validate a document, expand plugin components, return it with needed capabilities."""
        try:
            doc = PresentationDocument.model_validate(document)
        except ValidationError as exc:
            raise ValidationFailed("invalid presentation", errors=_errors(exc)) from exc
        counter = [0]
        needed: set[str] = {"display.text"}
        components = [self._component(c, 0, counter, needed) for c in doc.components]
        if doc.layout == "dashboard":
            needed.add("display.dashboard")
        return {**doc.model_dump(exclude_none=True), "components": components}, needed

    def _component(self, raw: dict[str, Any], depth: int, counter: list[int],
                   needed: set[str]) -> dict[str, Any]:
        counter[0] += 1
        if counter[0] > MAX_COMPONENTS:
            raise ValidationFailed("too many components")
        if depth > MAX_DEPTH:
            raise ValidationFailed("components nested too deeply")
        ctype = raw.get("type")
        props = {k: v for k, v in raw.items() if k != "type"}
        if not isinstance(ctype, str):
            raise ValidationFailed("component without type")
        if ctype in BUILTIN:
            try:
                model = BUILTIN[ctype].model_validate(props)
            except ValidationError as exc:
                raise ValidationFailed(f"invalid {ctype} component", errors=_errors(exc)) from exc
            data = model.model_dump(exclude_none=True)
            if ctype in REQUIRED_CAPABILITY:
                needed.add(REQUIRED_CAPABILITY[ctype])
            if ctype in CONTAINERS:
                data["children"] = [self._component(c, depth + 1, counter, needed)
                                    for c in data["children"]]
            if ctype == "image":
                needed.add("display.image")
            return {"type": ctype, **data}
        plugin = self._plugin.get(ctype)
        if plugin is None:
            raise ValidationFailed(f"unknown component type {ctype}")
        spec, _ = plugin
        try:
            jsonschema.validate(props, spec.props_schema)
        except jsonschema.ValidationError as exc:
            raise ValidationFailed(f"invalid {ctype} props: {exc.message}") from exc
        expanded = _fill(spec.template, props)
        if not isinstance(expanded, dict):
            raise ValidationFailed(f"template of {ctype} must produce a component")
        return self._component(expanded, depth + 1, counter, needed)


_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _lookup(props: dict[str, Any], path: str) -> Any:
    value: Any = props
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _fill(template: Any, props: dict[str, Any]) -> Any:
    """Substitute ``{{prop}}`` placeholders. A string that is exactly one placeholder
    keeps the prop's type (so lists/numbers can be passed through)."""
    if isinstance(template, dict):
        return {k: _fill(v, props) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, props) for v in template]
    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template.strip())
        if whole:
            return _lookup(props, whole.group(1))
        return _PLACEHOLDER.sub(lambda m: str(_lookup(props, m.group(1)) or ""), template)
    return template


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
