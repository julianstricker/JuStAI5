"""System prompt: home location, time zone and what to do when a capability is missing."""

from justai.ai.config import AISettings
from justai.conversation.context import ConversationContext, build_system_prompt


def _ctx(**kw: object) -> ConversationContext:
    return ConversationContext(session_id="s", endpoint_name=None, room_id=None, room_name=None, **kw)  # type: ignore[arg-type]


def test_home_location_is_the_reference_for_nearby_questions() -> None:
    prompt = build_system_prompt(AISettings(), _ctx(home_location="Bolzano, South Tyrol"), [])
    assert "The home is located in Bolzano, South Tyrol." in prompt
    assert "nearest" in prompt


def test_no_home_location_no_line() -> None:
    assert "The home is located" not in build_system_prompt(AISettings(), _ctx(), [])


def test_time_zone_comes_from_the_context() -> None:
    prompt = build_system_prompt(AISettings(), _ctx(timezone="America/New_York"), [])
    assert "(America/New_York)" in prompt


def test_missing_capability_leads_to_tools_develop() -> None:
    prompt = build_system_prompt(AISettings(), _ctx(), [])
    assert "tools.develop" in prompt
    assert "Never claim you cannot do something" in prompt
