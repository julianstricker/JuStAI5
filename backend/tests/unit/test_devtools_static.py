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
    assert any("Syntax" in i for i in static_check("def broken(:", "", []))
