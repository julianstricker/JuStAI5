"""Automation definition model (validated; stored as JSONB)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ triggers


class EventTrigger(_M):
    type: Literal["event"] = "event"
    event: str = Field(description="Event type, wildcards allowed (e.g. vision.object.*)")
    match: dict[str, Any] = Field(default_factory=dict, description="payload fields that must be equal")
    room_id: str | None = Field(None, description="only events from this room")


class CronTrigger(_M):
    type: Literal["cron"] = "cron"
    cron: str = Field(description="5 fields: minute hour day month weekday (0=Sunday)")
    room_id: str | None = None

    @field_validator("cron")
    @classmethod
    def _valid(cls, v: str) -> str:
        from justai.automation.cron import CronExpr

        CronExpr(v)
        return v


class IntervalTrigger(_M):
    type: Literal["interval"] = "interval"
    seconds: int = Field(ge=30)
    room_id: str | None = None


class AtTrigger(_M):
    type: Literal["at"] = "at"
    at: datetime
    room_id: str | None = None


Trigger = Annotated[EventTrigger | CronTrigger | IntervalTrigger | AtTrigger, Field(discriminator="type")]


# ---------------------------------------------------------------- conditions


class TimeWindow(_M):
    type: Literal["time_window"] = "time_window"
    start: time
    end: time
    weekdays: list[int] | None = Field(None, description="0=Monday ... 6=Sunday")


class PayloadCondition(_M):
    type: Literal["payload"] = "payload"
    path: str = Field(description="dotted path in the event payload, e.g. similarity")
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "contains"] = "=="
    value: Any = None


class NoActiveConversation(_M):
    type: Literal["no_active_conversation"] = "no_active_conversation"
    room: str = Field("trigger", description="'trigger' or a room id")


class StateCondition(_M):
    type: Literal["visual_state"] = "visual_state"
    detector: str
    state: str


Condition = Annotated[TimeWindow | PayloadCondition | NoActiveConversation | StateCondition,
                      Field(discriminator="type")]


# ------------------------------------------------------------------- actions


class InvokeAssistant(_M):
    type: Literal["assistant.invoke"] = "assistant.invoke"
    instruction: str = Field(description="What the assistant should do/say, e.g. 'Begrüße Julian'")
    room: str = Field("trigger", description="'trigger' (room of the triggering event) or a room id")
    start_conversation: bool = Field(True, description="keep listening after speaking")


class Speak(_M):
    type: Literal["speak"] = "speak"
    text: str
    room: str = "trigger"
    start_conversation: bool = Field(
        True, description="speak in the assistant's voice and listen for an answer (dialog); "
                          "false: plain announcement")


class ShowOnDisplay(_M):
    type: Literal["display.show"] = "display.show"
    document: dict[str, Any]
    room: str = "trigger"


class CallTool(_M):
    type: Literal["tool"] = "tool"
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class EmitEvent(_M):
    type: Literal["event.emit"] = "event.emit"
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Wait(_M):
    type: Literal["wait"] = "wait"
    seconds: float = Field(ge=0, le=3600)


Action = Annotated[InvokeAssistant | Speak | ShowOnDisplay | CallTool | EmitEvent | Wait,
                   Field(discriminator="type")]


class Options(_M):
    once: bool = Field(False, description="disable after the first successful run")
    cooldown_s: float = Field(0, ge=0)
    priority: int = Field(1, ge=0, le=3)
    max_retries: int = Field(2, ge=0, le=10)
    expires_at: datetime | None = None
    max_runs_per_hour: int = Field(20, ge=1, le=3600)


class AutomationDefinition(_M):
    trigger: Trigger
    conditions: list[Condition] = Field(default_factory=list)
    actions: list[Action] = Field(min_length=1, max_length=20)
    options: Options = Field(default_factory=Options)


def definition_schema() -> dict[str, Any]:
    return AutomationDefinition.model_json_schema()
