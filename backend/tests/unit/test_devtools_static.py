from justai.devtools.service import static_check

GOOD = '''
from justai_sdk import Plugin, ToolDefinition, ToolResult
from pydantic import BaseModel
import json, math

class P(BaseModel):
    x: int

class GeneratedPlugin(Plugin):
    async def setup(self):
        self.ctx.register_tool(ToolDefinition(name="calc.square", description="x", parameters=P), self.sq)

    async def sq(self, p, ctx):
        return ToolResult.success(p.x * p.x)
'''


def test_clean_code_passes() -> None:
    assert static_check(GOOD, "def test_x():\n    assert True\n", ["tools.provide"]) == []


def test_dangerous_constructs_are_reported() -> None:
    bad = GOOD + "\nimport subprocess\nfrom os import system\nx = eval('1')\ny = ().__class__.__subclasses__()\n"
    issues = static_check(bad, "", ["tools.provide", "system.manage"])
    text = " ".join(issues)
    for needle in ("subprocess", "os", "eval", "__subclasses__", "system.manage"):
        assert needle in text


def test_syntax_error_reported() -> None:
    assert any("syntax error" in i for i in static_check("def broken(:", "", []))


def test_missing_settings_are_required_fields_without_value_or_default() -> None:
    from justai.devtools.service import missing_settings

    schema = {"type": "object", "required": ["api_key", "threshold", "place"],
              "properties": {"api_key": {"type": "string"}, "threshold": {"type": "number", "default": 20},
                             "place": {"type": "string"}}}
    assert missing_settings(schema, {"place": "Bozen"}) == ["api_key"]
    assert missing_settings(schema, {"api_key": "x", "place": "Bozen"}) == []
    assert missing_settings({"type": "object"}, {}) == []


def test_fake_context_runs_background_jobs_and_records_events() -> None:
    import asyncio

    from justai_sdk import Plugin
    from justai_sdk.events import Event
    from justai_sdk.manifest import PluginManifest
    from justai_sdk.testing import FakePluginContext

    class Watcher(Plugin):
        async def setup(self) -> None:
            self.ctx.register_event_type("cheap", "Price below threshold")
            self.ctx.run_every(300, self.check, name="price")
            self.calls = 0

        async def check(self) -> None:
            self.calls += 1
            await self.ctx.publish(Event(type=f"plugin.{self.ctx.plugin_id}.cheap", payload={"price": 18}))

    manifest = PluginManifest.model_validate({
        "id": "gen-watch", "name": "Watch", "version": "1.0.1", "types": ["tool"],
        "entrypoint": "plugin:Watcher", "permissions": ["events.publish"]})
    ctx = FakePluginContext(manifest)
    plugin = Watcher(ctx)

    async def run() -> None:
        await plugin.setup()
        await ctx.run_jobs()

    asyncio.run(run())
    assert ctx.event_types == {"plugin.gen-watch.cheap": "Price below threshold"}
    assert [e.type for e in ctx.events] == ["plugin.gen-watch.cheap"] and plugin.calls == 1


def test_generation_prompt_formats() -> None:
    from justai.devtools.service import ALLOWED_PERMISSIONS, GEN_PROMPT

    text = GEN_PROMPT.format(permissions=", ".join(sorted(ALLOWED_PERMISSIONS)), example="EXAMPLE")
    assert "EXAMPLE" in text and "run_every" in text and "payload={...}" in text


def test_fake_http_routes_accept_data_answers() -> None:
    import asyncio

    from justai_sdk.plugin import HttpResponse
    from justai_sdk.testing import FakeHttp

    http = FakeHttp(["api.open-meteo.com"], {
        "https://api.open-meteo.com/v1/forecast*": {"current": {"rain": 0.4}},
        "api.open-meteo.com/v1/text*": "plain",
        "*/v1/fn*": lambda m, u, p, j: HttpResponse(status=201, text="fn"),
    })

    async def run() -> list[object]:
        a = await http.get("https://api.open-meteo.com/v1/forecast?x=1")
        b = await http.get("https://api.open-meteo.com/v1/text")
        c = await http.get("https://api.open-meteo.com/v1/fn")
        return [a.json(), b.text, c.status]

    assert asyncio.run(run()) == [{"current": {"rain": 0.4}}, "plain", 201]
