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


def test_recognition_rules_get_a_default_absence_condition() -> None:
    from justai.automation.extension import DEFAULT_AWAY_S, add_default_absence

    raw = {"trigger": {"type": "event", "event": "vision.person.recognized", "match": {"person_id": "p1"}},
           "actions": [{"type": "speak", "text": "Hallo"}]}
    d = AutomationService.validate(add_default_absence(raw))
    assert [(c.path, c.op, c.value) for c in d.conditions] == [("away_s", ">=", DEFAULT_AWAY_S)]
    explicit = {**raw, "conditions": [{"type": "payload", "path": "away_s", "op": ">=", "value": 0}]}
    assert add_default_absence(explicit) == explicit
    other = {"trigger": {"type": "event", "event": "vision.object.appeared"}, "actions": raw["actions"]}
    assert add_default_absence(other) == other


def test_not_before_and_expires_at_guard_triggers_in_local_time() -> None:
    """'Wenn du mich ab morgen 9 Uhr siehst …': triggers before not_before are ignored; times
    without a zone (as models write them) are system time, not a crash or UTC."""
    import asyncio
    from datetime import timedelta
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from justai.automation.engine import AutomationEngine
    from justai.automation.model import AutomationDefinition

    tz = ZoneInfo("Europe/Rome")
    queued: list[str] = []

    class _Service:
        async def update(self, *_: object, **__: object) -> None:
            return None

    class _Jobs:
        async def enqueue(self, kind: str, *_: object, **__: object) -> None:
            queued.append(kind)

    engine = AutomationEngine(SimpleNamespace(conversations=SimpleNamespace(active=list)),  # type: ignore[arg-type]
                              _Service(), bus=None, jobs=_Jobs())  # type: ignore[arg-type]

    async def reload() -> None:
        return None

    engine.reload = reload  # type: ignore[method-assign]

    def definition(**options: str) -> AutomationDefinition:
        return AutomationDefinition.model_validate({
            "trigger": {"type": "event", "event": "vision.person.recognized"},
            "actions": [{"type": "speak", "text": "Müll rausbringen", "room": "trigger"}],
            "options": {"once": True, **options}})

    def local(delta: timedelta) -> str:  # naive local time, like the model writes it
        return (datetime.now(tz) + delta).replace(tzinfo=None).isoformat(timespec="seconds")

    def run(d: AutomationDefinition) -> bool:
        auto = SimpleNamespace(id="a1", state={})
        return asyncio.run(engine._maybe_queue(auto, d, None))  # type: ignore[arg-type]

    assert run(definition(not_before=local(timedelta(minutes=30)))) is False
    assert run(definition(not_before=local(timedelta(minutes=-1)))) is True
    assert run(definition(expires_at=local(timedelta(minutes=-1)))) is False
    assert run(definition(expires_at=local(timedelta(hours=1)))) is True
    assert queued == ["automation.run", "automation.run"]
