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
                "config": {"conversation": {"mode": "pipeline", "inactivity_timeout_s": 12},
                           "audio": {"duplex": "half", "output_latency_ms": 900}}}))
            self.endpoints[name] = ep["id"]
        assert wait_for(lambda: all(ok(api.get(f"/api/endpoints/{e}"))["runtime"] for e in self.endpoints.values()), 20)

    def say(self, room: str, text: str, also: list[str] | None = None,
            voice: str = "en_US-lessac-medium") -> None:
        result = ok(self.api.post("/api/tools/simulator.say/execute", json={
            "args": {"device_id": self.devices[room], "text": text, "voice": voice,
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


def test_display_pairing_presentation_ack_and_room_routing(world: World) -> None:
    """Criteria 14/15: a display in the room shows the content and the tool only reports
    success after the display acknowledged it."""
    import asyncio
    import json

    import websockets

    api = world.api
    ws_url = BASE.replace("http", "ws", 1) + "/api/display/ws"  # type: ignore[union-attr]
    received: list[dict[str, Any]] = []

    async def display_client() -> dict[str, Any]:
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type": "hello", "token": None, "user_agent": "e2e",
                                      "capabilities": ["display.text", "display.dashboard", "display.image"]}))
            code = json.loads(await ws.recv())["code"]
            approve = await asyncio.to_thread(api.post, f"/api/displays/pairing/{code}/approve",
                                              json={"name": "E2E TV", "room_id": world.rooms["Wohnzimmer"]})
            device_id = approve.json()["device_id"]
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                received.append(msg)
                if msg["type"] == "ready":
                    break
            # Wait until the core sees the display online, then ask the assistant's tool to show something.
            for _ in range(40):
                d = await asyncio.to_thread(api.get, f"/api/devices/{device_id}")
                if d.json()["status"] == "online":
                    break
                await asyncio.sleep(0.5)
            call = asyncio.ensure_future(asyncio.to_thread(api.post, "/api/tools/display.show/execute", json={
                "room_id": world.rooms["Wohnzimmer"],
                "args": {"document": {"title": "Börse", "components": [
                    {"type": "stock-quote", "symbol": "AAPL", "price": 1.0, "currency": "USD"}]}}}))
            show = json.loads(await asyncio.wait_for(ws.recv(), 30))
            while show["type"] != "show":
                show = json.loads(await asyncio.wait_for(ws.recv(), 30))
            assert not call.done(), "tool must wait for the display acknowledgement"
            await ws.send(json.dumps({"type": "ack", "presentation_id": show["presentation_id"],
                                      "status": "displayed"}))
            result = (await call).json()
            await asyncio.to_thread(api.delete, f"/api/devices/{device_id}")
            return result

    result = asyncio.run(display_client())
    assert result["ok"], result
    assert result["data"]["status"] == "displayed"


def test_automation_greets_recognised_person_in_the_trigger_room(world: World) -> None:
    """Criterion 13 (with the recognition event injected): proactive conversation
    without wakeword in the room where the person was seen."""
    api = world.api
    person = ok(api.post("/api/people", json={"name": f"E2E Julian {uuid.uuid4().hex[:4]}"}))
    auto = ok(api.post("/api/automations", json={
        "name": "E2E greet", "definition": {
            "trigger": {"type": "event", "event": "vision.person.recognized", "match": {"person_id": person["id"]}},
            "actions": [{"type": "assistant.invoke", "instruction": "Begrüße die Person kurz mit ihrem Namen.",
                         "room": "trigger"}],
            "options": {"once": True}}}))
    try:
        ok(api.post("/api/events", json={
            "type": "vision.person.recognized", "room_id": world.rooms["Wohnzimmer"],
            "payload": {"person_id": person["id"], "camera_id": "sim", "similarity": 0.61, "match_level": "strong"}}))
        greeted = wait_for(lambda: (s := world.session("Wohnzimmer")) and any(
            t["role"] == "assistant" for t in s["transcript"]) and s, 60)
        assert greeted, "no proactive greeting"
        assert world.session("Kueche") is None
        runs = ok(api.get(f"/api/automations/{auto['id']}/runs"))
        assert runs and runs[0]["status"] == "succeeded"
        # once=True: a second recognition does not greet again
        auto_state = next(a for a in ok(api.get("/api/automations")) if a["id"] == auto["id"])
        assert auto_state["enabled"] is False
        api.post(f"/api/conversations/{greeted['id']}/end")
    finally:
        api.delete(f"/api/automations/{auto['id']}")
        api.delete(f"/api/people/{person['id']}")


def test_wakeword_shortly_after_continues_the_conversation_only_for_the_same_voice(world: World) -> None:
    api = world.api
    ok(api.patch(f"/api/endpoints/{world.endpoints['Wohnzimmer']}", json={"config": {
        "conversation": {"mode": "pipeline", "inactivity_timeout_s": 8, "resume_window_s": 300,
                         "speaker_check": True},
        "audio": {"duplex": "half", "output_latency_ms": 900}}}))
    time.sleep(2)

    def run_turn(text: str, voice: str) -> dict[str, Any]:
        world.say("Wohnzimmer", "Hey Jarvis!", voice=voice)
        s = wait_for(lambda: world.session("Wohnzimmer"), 15)
        assert s, "wakeword did not start a session"
        time.sleep(1.0)
        world.say("Wohnzimmer", text, voice=voice)
        assert wait_for(lambda: (x := world.session("Wohnzimmer")) and any(
            t["role"] == "assistant" for t in x["transcript"]), 60), "no answer"
        assert wait_for(lambda: world.session("Wohnzimmer") is None, 45), "session did not end"
        events = ok(api.get("/api/events", params={"type": "conversation.session.started", "limit": 20}))
        return next(e["payload"] for e in events if e["payload"].get("endpoint_id") == world.endpoints["Wohnzimmer"])

    first = run_turn("What is the capital of Italy? One short sentence.", "en_US-lessac-medium")
    assert first.get("resumed_from") is None
    second = run_turn("And how many people live there? One short sentence.", "en_US-lessac-medium")
    assert second.get("resumed_from"), "same voice within the window should continue"
    third = run_turn("What is two plus three? Number only.", "it_IT-paola-medium")
    assert third.get("resumed_from") is None, "another voice must start a new conversation"


def test_speak_automation_starts_a_dialog_in_the_assistant_voice(world: World) -> None:
    api = world.api
    auto = ok(api.post("/api/automations", json={
        "name": "E2E speak", "definition": {
            "trigger": {"type": "event", "event": "manual.test", "match": {"e2e": "speak"}},
            "actions": [{"type": "speak", "text": "Hallo, hier ist ein Test.", "room": "trigger"}]}}))
    try:
        ok(api.post("/api/events", json={"type": "manual.test", "room_id": world.rooms["Wohnzimmer"],
                                          "payload": {"e2e": "speak"}}))
        s = wait_for(lambda: (x := world.session("Wohnzimmer")) and any(
            t["role"] == "assistant" for t in x["transcript"]) and x, 60)
        assert s, "speak action did not start a conversation"
        said = " ".join(t["text"] for t in s["transcript"] if t["role"] == "assistant")
        assert "Test" in said
        # It keeps listening: the person can answer within the inactivity time.
        assert s["state"] in ("listening", "speaking", "processing")
        api.post(f"/api/conversations/{s['id']}/end")
    finally:
        api.delete(f"/api/automations/{auto['id']}")


def test_voice_profile_enrolled_in_conversation_identifies_the_speaker_later(world: World) -> None:
    api = world.api
    ok(api.patch(f"/api/endpoints/{world.endpoints['Wohnzimmer']}", json={"config": {
        "conversation": {"mode": "pipeline", "inactivity_timeout_s": 10, "resume_window_s": 0},
        "audio": {"duplex": "half", "output_latency_ms": 900}}}))
    name = "Annika"
    before_ids = {p["id"] for p in ok(api.get("/api/people"))}
    time.sleep(2)

    def new_with_voice() -> dict[str, Any] | None:
        return next((p for p in ok(api.get("/api/people"))
                     if p["id"] not in before_ids and p.get("voice_count")), None)

    def assistant_count() -> int:
        s = world.session("Wohnzimmer")
        return sum(1 for t in (s or {}).get("transcript", []) if t["role"] == "assistant")

    def say_and_wait(text: str, voice: str = "en_US-lessac-medium") -> None:
        before = assistant_count()
        world.say("Wohnzimmer", text, voice=voice)
        assert wait_for(lambda: assistant_count() > before, 60), f"no answer to: {text}"
        time.sleep(1.5)

    try:
        world.say("Wohnzimmer", "Hey Jarvis!")
        assert wait_for(lambda: world.session("Wohnzimmer"), 15)
        time.sleep(1.0)
        say_and_wait(f"Hello, my name is {name}. Please save my voice profile so that you recognise "
                     "me by my voice from now on. I agree to that.")
        if not new_with_voice():
            say_and_wait("Yes, I confirm. Please save my voice profile now.")
        person = wait_for(new_with_voice, 20)
        assert person, "voice profile was not stored"
        s = world.session("Wohnzimmer")
        if s:
            api.post(f"/api/conversations/{s['id']}/end")
        assert wait_for(lambda: world.session("Wohnzimmer") is None, 30)

        def started_person(voice: str) -> str | None:
            world.say("Wohnzimmer", "Hey Jarvis!", voice=voice)
            sess = wait_for(lambda: world.session("Wohnzimmer"), 15)
            assert sess, "wakeword did not start a session"
            api.post(f"/api/conversations/{sess['id']}/end")
            assert wait_for(lambda: world.session("Wohnzimmer") is None, 30)
            events = ok(api.get("/api/events", params={"type": "conversation.session.started", "limit": 5}))
            ev = next(e for e in events if e["payload"].get("endpoint_id") == world.endpoints["Wohnzimmer"])
            return ev["payload"].get("person_id")

        assert started_person("en_US-lessac-medium") == person["id"], "same voice not recognised"
        assert started_person("it_IT-paola-medium") != person["id"], "other voice taken for the person"
    finally:
        for p in ok(api.get("/api/people")):
            if p["id"] not in before_ids:
                api.delete(f"/api/people/{p['id']}")


def test_voice_profile_core_without_llm(world: World) -> None:
    """Enrol from real conversation speech, then identify on the wake phrase (no LLM needed)."""
    api = world.api
    ok(api.patch(f"/api/endpoints/{world.endpoints['Wohnzimmer']}", json={"config": {
        "conversation": {"mode": "pipeline", "inactivity_timeout_s": 20, "resume_window_s": 0},
        "audio": {"duplex": "half", "output_latency_ms": 900}}}))
    before_ids = {p["id"] for p in ok(api.get("/api/people"))}
    time.sleep(2)

    def wake(voice: str) -> dict[str, Any]:
        world.say("Wohnzimmer", "Hey Jarvis!", voice=voice)
        s = wait_for(lambda: world.session("Wohnzimmer"), 15)
        assert s, "wakeword did not start a session"
        return s

    def end_session() -> None:
        s = world.session("Wohnzimmer")
        if s:
            api.post(f"/api/conversations/{s['id']}/end")
        assert wait_for(lambda: world.session("Wohnzimmer") is None, 30)

    def started_person() -> str | None:
        events = ok(api.get("/api/events", params={"type": "conversation.session.started", "limit": 5}))
        ev = next(e for e in events if e["payload"].get("endpoint_id") == world.endpoints["Wohnzimmer"])
        return ev["payload"].get("person_id")

    try:
        session = wake("en_US-lessac-medium")
        time.sleep(1.0)
        world.say("Wohnzimmer", "Today I would like to tell you a little about my garden, the roses and "
                  "the old apple tree that my grandfather planted many years ago.")
        time.sleep(11.0)  # the simulator plays the sentence in real time
        result = ok(api.post("/api/tools/identity.register_voice/execute", json={
            "args": {"name": "Voice Test Person"}, "session_id": session["id"], "confirmed": True}))
        assert result["ok"], result
        person = next(p for p in ok(api.get("/api/people")) if p["id"] not in before_ids)
        assert person["voice_count"] >= 2
        end_session()

        wake("en_US-lessac-medium")
        time.sleep(1.5)
        assert started_person() == person["id"], "same voice was not recognised"
        end_session()
        wake("it_IT-paola-medium")
        time.sleep(1.5)
        assert started_person() != person["id"], "another voice was taken for the person"
        end_session()
    finally:
        for p in ok(api.get("/api/people")):
            if p["id"] not in before_ids:
                api.delete(f"/api/people/{p['id']}")


def test_realtime_mode_conversation_with_language_and_vocabulary(world: World) -> None:
    """The mode used in production (Gemini Live): wakeword, German question, answer in the room."""
    api = world.api
    ok(api.patch(f"/api/endpoints/{world.endpoints['Wohnzimmer']}", json={"config": {
        "conversation": {"mode": "realtime", "inactivity_timeout_s": 10, "resume_window_s": 0},
        "audio": {"duplex": "half", "output_latency_ms": 900}}}))
    time.sleep(2)
    world.say("Wohnzimmer", "Hey Jarvis!")
    assert wait_for(lambda: world.session("Wohnzimmer"), 15), "wakeword did not start a session"
    time.sleep(1.5)
    world.say("Wohnzimmer", "Wie heißt die Hauptstadt von Frankreich? Antworte in einem kurzen Satz.",
              voice="de_DE-thorsten-medium")
    s = wait_for(lambda: (x := world.session("Wohnzimmer")) and any(
        t["role"] == "assistant" and "paris" in t["text"].lower() for t in x["transcript"]) and x, 60)
    assert s, f"no realtime answer: {world.session('Wohnzimmer')}"
    user = " ".join(t["text"] for t in s["transcript"] if t["role"] == "user").lower()
    assert "frankreich" in user, f"German speech not transcribed as German: {user!r}"
    api.post(f"/api/conversations/{s['id']}/end")


def test_device_app_streams_microphone_camera_and_receives_speech(world: World) -> None:
    """A phone/tablet/PC running the device app: pairing, auto endpoint, camera, mic -> answer audio."""
    import asyncio
    import json
    import os

    import numpy as np
    import websockets

    models = os.environ.get("JUSTAI_TEST_MODELS_DIR")
    if not models:
        pytest.skip("JUSTAI_TEST_MODELS_DIR needed to synthesise the test speech")
    from piper import PiperVoice

    def speech(text: str) -> np.ndarray:
        voice = PiperVoice.load(f"{models}/piper/en_US-lessac-medium.onnx")
        pcm = np.concatenate([c.audio_int16_array for c in voice.synthesize(text)])
        idx = np.arange(0, pcm.size, voice.config.sample_rate / 16000).astype(int)
        return pcm[idx[idx < pcm.size]]

    api = world.api
    ws_url = BASE.replace("http", "ws", 1) + "/api/display/ws"  # type: ignore[union-attr]
    room = world.rooms["Kueche"]
    jpeg = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300") + bytes(64) + b"\xff\xd9"

    async def device() -> dict[str, Any]:
        caps = ["display.text", "audio.input", "audio.output", "video.input", "camera.snapshot"]
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "hello", "token": None, "user_agent": "e2e-app", "capabilities": caps}))
            code = json.loads(await ws.recv())["code"]
            device_id = (await asyncio.to_thread(api.post, f"/api/displays/pairing/{code}/approve",
                                                 json={"name": "E2E Handy", "room_id": room})).json()["device_id"]
            received = {"speaker_bytes": 0}

            async def reader() -> None:
                async for msg in ws:
                    if isinstance(msg, bytes) and msg[:1] == b"\x11":
                        received["speaker_bytes"] += len(msg) - 1

            reader_task = asyncio.create_task(reader())

            async def stream(pcm: np.ndarray) -> None:
                for i in range(0, pcm.size, 320):  # 20 ms frames in real time
                    frame = pcm[i:i + 320]
                    if frame.size < 320:
                        frame = np.pad(frame, (0, 320 - frame.size))
                    await ws.send(b"\x01" + frame.astype("<i2").tobytes())
                    await asyncio.sleep(0.02)

            await ws.send(b"\x02" + jpeg)
            for _ in range(40):  # device online, endpoint wired
                eps = (await asyncio.to_thread(api.get, "/api/endpoints")).json()
                ep = next((e for e in eps if any(d["device_id"] == device_id for d in e["devices"])), None)
                if ep and ep.get("runtime"):
                    break
                await asyncio.sleep(0.5)
            assert ep, "no endpoint was created for the device app"
            roles = sorted(d["role"] for d in ep["devices"])
            snap = await asyncio.to_thread(api.get, f"/api/devices/{device_id}/snapshot.jpg")
            silence = np.zeros(16000, np.int16)
            await stream(np.concatenate([silence, speech("Hey Jarvis!"), silence]))
            await stream(np.concatenate([speech("What is the capital of Spain? Answer in one short sentence."),
                                         np.zeros(16000 * 2, np.int16)]))
            for _ in range(60):
                if received["speaker_bytes"] > 16000:  # > 0.5 s of answer audio
                    break
                await stream(np.zeros(16000, np.int16))  # keep the microphone running
            sessions = (await asyncio.to_thread(api.get, "/api/conversations/active")).json()
            session = next((s for s in sessions if s["endpoint_id"] == ep["id"]), None)
            reader_task.cancel()
            if session:
                await asyncio.to_thread(api.post, f"/api/conversations/{session['id']}/end")
            await asyncio.to_thread(api.delete, f"/api/endpoints/{ep['id']}")
            await asyncio.to_thread(api.delete, f"/api/devices/{device_id}")
            return {"roles": roles, "snapshot": snap.status_code == 200 and snap.content == jpeg,
                    "speaker_bytes": received["speaker_bytes"], "session": session}

    result = asyncio.run(device())
    assert result["roles"] == ["camera", "display", "mic", "speaker"]
    assert result["snapshot"], "camera frame not available as snapshot"
    assert result["session"], "wakeword over the device app did not start a conversation"
    user = " ".join(t["text"] for t in result["session"]["transcript"] if t["role"] == "user").lower()
    assert "spain" in user, user
    assert result["speaker_bytes"] > 16000, "no answer audio reached the device"
