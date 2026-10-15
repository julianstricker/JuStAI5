from datetime import datetime

import pytest

from justai.automation.cron import CronExpr
from justai.automation.engine import AutomationService, compare
from justai.common.errors import ValidationFailed


def test_greeting_definition_is_valid() -> None:
    d = AutomationService.validate({
        "trigger": {"type": "event", "event": "vision.person.recognized", "match": {"person_id": "p1"}},
        "actions": [{"type": "assistant.invoke", "instruction": "Begrüße Julian", "room": "trigger"}],
        "options": {"once": True},
    })
    assert d.options.once and d.actions[0].type == "assistant.invoke"


def test_invalid_definitions_are_rejected() -> None:
    with pytest.raises(ValidationFailed):
        AutomationService.validate({"trigger": {"type": "event", "event": "x"}, "actions": []})
    with pytest.raises(ValidationFailed):
        AutomationService.validate({"trigger": {"type": "cron", "cron": "99 * * * *"},
                                    "actions": [{"type": "speak", "text": "x"}]})
    with pytest.raises(ValidationFailed):
        AutomationService.validate({"trigger": {"type": "event", "event": "x"},
                                    "actions": [{"type": "shell", "cmd": "rm -rf /"}]})


def test_cron_matching() -> None:
    weekday_morning = CronExpr("30 7 * * 1-5")
    assert weekday_morning.matches(datetime(2026, 10, 14, 7, 30))  # Wednesday
    assert not weekday_morning.matches(datetime(2026, 10, 18, 7, 30))  # Sunday
    assert CronExpr("*/15 * * * *").matches(datetime(2026, 1, 1, 0, 45))
    assert not CronExpr("*/15 * * * *").matches(datetime(2026, 1, 1, 0, 46))


@pytest.mark.parametrize(("left", "op", "right", "expected"), [
    (0.9, ">=", 0.5, True), ("a", "in", ["a", "b"], True), ("x", "==", "y", False),
    (None, ">", 1, False), ("hello", "contains", "ell", True),
])
def test_compare(left, op, right, expected) -> None:  # type: ignore[no-untyped-def]
    assert compare(left, op, right) is expected


def test_tool_definitions_without_type_are_normalized() -> None:
    from justai.automation.extension import normalize_definition

    raw = {"trigger": {"event": "vision.person.recognized", "match": {"person_id": "person-1"}},
           "conditions": [{"start": "07:00", "end": "22:00"}],
           "actions": [{"room": "trigger", "instruction": "Begrüße Anna"}, {"text": "Hallo"},
                       {"name": "weather.current", "args": {}}],
           "options": {"once": True}}
    d = AutomationService.validate(normalize_definition(raw))
    assert d.trigger.type == "event"
    assert [a.type for a in d.actions] == ["assistant.invoke", "speak", "tool"]
    assert d.conditions[0].type == "time_window"
