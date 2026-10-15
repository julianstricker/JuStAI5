"""End-to-end tests against a running JuStAI5 instance with simulated devices.

Covers acceptance criteria 2-8 without hardware: real wakeword model, real local
STT/TTS, the configured LLM, simulated rooms with acoustic echo.

Run:  JUSTAI_E2E_URL=http://localhost:8080 JUSTAI_E2E_PASSWORD=... pytest tests/e2e -m e2e
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

BASE = os.environ.get("JUSTAI_E2E_URL")
PASSWORD = os.environ.get("JUSTAI_E2E_PASSWORD")


@pytest.fixture(scope="module")
def api() -> Iterator[httpx.Client]:
    if not BASE or not PASSWORD:
        pytest.skip("JUSTAI_E2E_URL / JUSTAI_E2E_PASSWORD not set")
    client = httpx.Client(base_url=BASE, timeout=120, headers={"x-justai": "1"})
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()["token"]
    client.headers["authorization"] = f"Bearer {token}"
    yield client
    client.close()


def ok(r: httpx.Response) -> Any:
    assert r.status_code < 300, r.text
    return r.json()


def wait_for(fn: Any, timeout: float, interval: float = 0.5) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return None


class World:
    """Two simulated rooms, each with a camera+mic+speaker device and an endpoint."""

    def __init__(self, api: httpx.Client, *, separate_groups: bool) -> None:
        self.api = api
        tag = uuid.uuid4().hex[:6]
        self.rooms: dict[str, str] = {}
        self.devices: dict[str, str] = {}
        self.endpoints: dict[str, str] = {}
        for name in ("Wohnzimmer", "Kueche"):
            room = ok(api.post("/api/rooms", json={"name": f"E2E {name} {tag}"}))
            self.rooms[name] = room["id"]
            device = ok(api.post("/api/devices", json={
                "name": f"Sim {name} {tag}", "driver_id": "simulated", "room_id": room["id"],
                "config": {"echo_delay_s": 0.6, "echo_gain": 0.5, "camera": False}}))
            self.devices[name] = device["id"]
        for name in self.rooms:
            ok_device = wait_for(
                lambda n=name: ok(api.get(f"/api/devices/{self.devices[n]}"))["status"] == "online", 30)
            assert ok_device, f"simulated device {name} did not come online"
            ep = ok(api.post("/api/endpoints", json={
                "name": f"E2E {name} {tag}", "room_id": self.rooms[name],
                "arbitration_group": f"{name}-{tag}" if separate_groups else f"house-{tag}",
                "devices": [{"device_id": self.devices[name], "role": r} for r in ("mic", "speaker")],
                "config": {"conversation": {"mode": "pipeline", "inactivity_timeout_s": 8},
                           "audio": {"duplex": "half", "output_latency_ms": 900}}}))
            self.endpoints[name] = ep["id"]
        assert wait_for(lambda: all(ok(api.get(f"/api/endpoints/{e}"))["runtime"] for e in self.endpoints.values()), 20)

    def say(self, room: str, text: str, also: list[str] | None = None) -> None:
        result = ok(self.api.post("/api/tools/simulator.say/execute", json={
            "args": {"device_id": self.devices[room], "text": text, "voice": "en_US-lessac-medium",
                     "also_devices": [self.devices[r] for r in also or []], "also_gain": 0.5}}))
        assert result["ok"], result

    def session(self, room: str) -> dict[str, Any] | None:
        for s in ok(self.api.get("/api/conversations/active")):
            if s["endpoint_id"] == self.endpoints[room]:
                return s
        return None

    def speaker_frames(self, room: str) -> int:
        t = ok(self.api.get("/api/telemetry", params={"prefix": f"audio.speaker.{self.devices[room]}"}))
        data = next(iter(t.values()), {"data": {"frames": 0}})["data"]
        return int(data["frames"])

    def cleanup(self) -> None:
        for e in self.endpoints.values():
            self.api.delete(f"/api/endpoints/{e}")
        for d in self.devices.values():
            self.api.delete(f"/api/devices/{d}")
        for r in self.rooms.values():
            self.api.delete(f"/api/rooms/{r}")


@pytest.fixture
def world(api: httpx.Client) -> Iterator[World]:
    w = World(api, separate_groups=False)
    yield w
    w.cleanup()


@pytest.fixture
def separate_world(api: httpx.Client) -> Iterator[World]:
    w = World(api, separate_groups=True)
    yield w
    w.cleanup()


def test_wakeword_conversation_room_routing_echo_and_timeout(world: World) -> None:
    kitchen_frames_before = world.speaker_frames("Kueche")
    world.say("Wohnzimmer", "Hey Jarvis!")
    session = wait_for(lambda: world.session("Wohnzimmer"), 15)
    assert session, "wakeword did not start a session"
    assert world.session("Kueche") is None
    time.sleep(1.0)
    world.say("Wohnzimmer", "What is the capital of France? Please answer in one short sentence.")
    answered = wait_for(lambda: (s := world.session("Wohnzimmer")) and any(
        t["role"] == "assistant" for t in s["transcript"]) and s, 60)
    assert answered, "no answer"
    answer = next(t["text"] for t in answered["transcript"] if t["role"] == "assistant")
    assert "paris" in answer.lower()
    # Answer audio went to the living room speaker only.
    assert world.speaker_frames("Wohnzimmer") > 0
    assert world.speaker_frames("Kueche") == kitchen_frames_before
    # The assistant's own (echoed) speech must not become a new user turn, and the
    # session must end by inactivity.
    ended = wait_for(lambda: world.session("Wohnzimmer") is None, 45)
    assert ended, "session did not time out"
    history = ok(world.api.get("/api/conversations/history", params={"limit": 20}))
    sid = session["id"]
    row = next(h for h in history if h["id"] == sid)
    assert row["end_reason"] == "inactivity"
    turns = ok(world.api.get(f"/api/conversations/{sid}/turns"))
    assert [t["role"] for t in turns if t["role"] in ("user", "assistant")] == ["user", "assistant"]


def test_same_wakeword_in_two_rooms_starts_only_one_session(world: World) -> None:
    # The speaker stands in the living room; the kitchen mic hears the same words quieter.
    world.say("Wohnzimmer", "Hey Jarvis!", also=["Kueche"])
    assert wait_for(lambda: world.session("Wohnzimmer") or world.session("Kueche"), 15)
    time.sleep(3)
    active = [world.session("Wohnzimmer"), world.session("Kueche")]
    assert sum(1 for s in active if s) == 1, "both rooms started a session"
    assert active[0] is not None, "the louder (living room) microphone should win"
    for s in active:
        if s:
            world.api.post(f"/api/conversations/{s['id']}/end")


def test_parallel_conversations_in_two_rooms(separate_world: World) -> None:
    w = separate_world
    w.say("Wohnzimmer", "Hey Jarvis!")
    w.say("Kueche", "Hey Jarvis!")
    both = wait_for(lambda: w.session("Wohnzimmer") and w.session("Kueche"), 15)
    assert both, "parallel sessions were not started"
    time.sleep(1.0)
    w.say("Wohnzimmer", "How much is two plus two? Answer with the number only.")
    w.say("Kueche", "How much is three plus three? Answer with the number only.")

    def answers() -> dict[str, str] | None:
        out = {}
        for room in ("Wohnzimmer", "Kueche"):
            s = w.session(room)
            texts = [t["text"] for t in (s or {}).get("transcript", []) if t["role"] == "assistant"]
            if not texts:
                return None
            out[room] = texts[-1].lower()
        return out

    result = wait_for(answers, 90)
    assert result, "not both rooms answered"
    assert "4" in result["Wohnzimmer"] or "four" in result["Wohnzimmer"]
    assert "6" in result["Kueche"] or "six" in result["Kueche"]
    for room in ("Wohnzimmer", "Kueche"):
        s = w.session(room)
        if s:
            w.api.post(f"/api/conversations/{s['id']}/end")
