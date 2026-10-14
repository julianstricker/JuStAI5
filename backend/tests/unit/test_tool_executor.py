import asyncio

import pytest
from justai_sdk.tools import InvocationOrigin, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel

from justai.events import EventBus, build_core_catalog
from justai.tools.registry import ConfirmationManager, ToolExecutor, ToolRegistry


class EchoParams(BaseModel):
    text: str


async def echo(params: EchoParams, ctx: ToolContext) -> ToolResult:
    return ToolResult.success({"echo": params.text})


async def slow(params: EchoParams, ctx: ToolContext) -> ToolResult:
    await asyncio.sleep(5)
    return ToolResult.success()


class Turns:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, session_id: str) -> int:
        return self.count


@pytest.fixture
async def setup():
    bus = EventBus(build_core_catalog())
    reg = ToolRegistry()
    turns = Turns()
    ex = ToolExecutor(reg, bus, None, ConfirmationManager(turns))
    reg.register(ToolDefinition(name="test.echo", description="echo", parameters=EchoParams,
                                permissions=["memory.read"]), echo)
    reg.register(ToolDefinition(name="test.slow", description="slow", parameters=EchoParams,
                                timeout_s=0.1), slow)
    reg.register(ToolDefinition(name="test.critical", description="critical", parameters=EchoParams,
                                requires_confirmation=True), echo)
    yield reg, ex, turns
    await bus.close()


def ctx(perms=("memory.read",), session="s1") -> ToolContext:
    return ToolContext(call_id="c", origin=InvocationOrigin.CONVERSATION, session_id=session,
                       permissions=frozenset(perms))


async def test_success_and_llm_name_lookup(setup) -> None:
    reg, ex, _ = setup
    r = await ex.execute("test__echo", {"text": "hi"}, ctx())
    assert r.ok and r.data == {"echo": "hi"}


async def test_permission_denied(setup) -> None:
    _, ex, _ = setup
    r = await ex.execute("test.echo", {"text": "hi"}, ctx(perms=()))
    assert not r.ok and r.error_code == "permission_denied"


async def test_invalid_arguments(setup) -> None:
    _, ex, _ = setup
    r = await ex.execute("test.echo", {"wrong": 1}, ctx())
    assert r.error_code == "invalid_arguments"


async def test_timeout(setup) -> None:
    _, ex, _ = setup
    r = await ex.execute("test.slow", {"text": "x"}, ctx())
    assert r.error_code == "timeout"


async def test_unknown_tool(setup) -> None:
    _, ex, _ = setup
    assert (await ex.execute("nope.tool", {}, ctx())).error_code == "unknown_tool"


async def test_confirmation_requires_new_user_turn(setup) -> None:
    _, ex, turns = setup
    r = await ex.execute("test.critical", {"text": "x"}, ctx())
    assert r.needs_confirmation and r.confirmation_token
    # The model tries to confirm immediately, without the user answering -> refused.
    refused = await ex.confirm(r.confirmation_token, ctx())
    assert refused.error_code == "confirmation_invalid"
    turns.count += 1  # user said "ja"
    ok = await ex.confirm(r.confirmation_token, ctx())
    assert ok.ok and ok.data == {"echo": "x"}
    # tokens are single-use
    again = await ex.confirm(r.confirmation_token, ctx())
    assert again.error_code == "confirmation_invalid"


async def test_confirmation_bound_to_session(setup) -> None:
    _, ex, turns = setup
    r = await ex.execute("test.critical", {"text": "x"}, ctx(session="s1"))
    turns.count += 1
    other = await ex.confirm(r.confirmation_token, ctx(session="s2"))
    assert other.error_code == "confirmation_invalid"


def test_unregister_owner_removes_tools() -> None:
    reg = ToolRegistry()
    reg.register(ToolDefinition(name="p.x", description="x", parameters=EchoParams), echo, owner="p")
    assert reg.get("p.x") is not None
    assert reg.unregister_owner("p") == ["p.x"]
    assert reg.get("p.x") is None
