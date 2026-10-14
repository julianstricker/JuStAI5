import pytest
from justai_sdk.plugin import DisplayComponentSpec

from justai.common.errors import ValidationFailed
from justai.display.components import ComponentRegistry


def test_valid_dashboard_and_capabilities() -> None:
    reg = ComponentRegistry()
    doc, needed = reg.normalize({
        "title": "Börse",
        "layout": "dashboard",
        "components": [
            {"type": "stock-quote", "symbol": "AAPL", "price": 231.4, "change_pct": 1.2},
            {"type": "chart", "kind": "line", "series": [{"name": "AAPL", "points": [["09:30", 230.0]]}]},
        ],
    })
    assert doc["components"][0]["symbol"] == "AAPL"
    assert {"display.dashboard", "display.text"} <= needed


def test_unknown_component_rejected() -> None:
    with pytest.raises(ValidationFailed):
        ComponentRegistry().normalize({"components": [{"type": "html", "html": "<script>"}]})


def test_extra_props_rejected() -> None:
    with pytest.raises(ValidationFailed):
        ComponentRegistry().normalize({"components": [{"type": "text", "text": "x", "onclick": "y"}]})


def test_image_src_must_be_safe() -> None:
    with pytest.raises(ValidationFailed):
        ComponentRegistry().normalize({"components": [{"type": "image", "src": "javascript:alert(1)"}]})
    doc, needed = ComponentRegistry().normalize(
        {"components": [{"type": "image", "src": "https://example.org/a.png"}]})
    assert "display.image" in needed


def test_nested_containers_and_depth_limit() -> None:
    reg = ComponentRegistry()
    leaf: dict = {"type": "text", "text": "x"}
    for _ in range(8):
        leaf = {"type": "card", "children": [leaf]}
    with pytest.raises(ValidationFailed, match="deeply"):
        reg.normalize({"components": [leaf]})


def test_plugin_template_expansion() -> None:
    reg = ComponentRegistry()
    reg.register(DisplayComponentSpec(
        type="weatherplug.today",
        description="Heute",
        props_schema={"type": "object", "properties": {"city": {"type": "string"},
                                                        "temp": {"type": "number"}},
                      "required": ["city", "temp"], "additionalProperties": False},
        template={"type": "card", "title": "Wetter {{city}}",
                  "children": [{"type": "stat", "label": "Temperatur", "value": "{{temp}}", "unit": "°C"}]},
    ), owner="weatherplug")
    doc, _ = reg.normalize({"components": [{"type": "weatherplug.today", "city": "Bozen", "temp": 21.5}]})
    card = doc["components"][0]
    assert card["type"] == "card" and card["title"] == "Wetter Bozen"
    assert card["children"][0]["value"] == 21.5
    reg.unregister_owner("weatherplug")
    with pytest.raises(ValidationFailed):
        reg.normalize({"components": [{"type": "weatherplug.today", "city": "x", "temp": 1}]})


def test_plugin_template_cannot_smuggle_unknown_types() -> None:
    reg = ComponentRegistry()
    reg.register(DisplayComponentSpec(type="evil.c", description="", props_schema={"type": "object"},
                                      template={"type": "html", "html": "{{x}}"}), owner="evil")
    with pytest.raises(ValidationFailed):
        reg.normalize({"components": [{"type": "evil.c", "x": "<script>"}]})
