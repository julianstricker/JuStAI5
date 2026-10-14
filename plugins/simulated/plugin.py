"""Simulated devices for tests and demos (no hardware required)."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from justai_sdk.audio import AudioChunk
from justai_sdk.plugin import Plugin
from justai_sdk.ports.devices import BaseDeviceHandle, Capability, DeviceInfo, ProbeResult
from justai_sdk.ports.ptz import PtzCapabilities, PtzPosition, PtzPreset
from justai_sdk.simulation import AcousticParams, AcousticRoom
from justai_sdk.tools import ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

SR = 16000
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "microphone": {"type": "boolean", "default": True},
        "speaker": {"type": "boolean", "default": True},
        "camera": {"type": "boolean", "default": True},
        "ptz": {"type": "boolean", "default": False},
        "image": {"type": "string", "description": "Pfad zu einem Bild (Kamera bzw. PTZ-Panorama)"},
        "echo_delay_s": {"type": "number", "default": 0.8},
        "echo_gain": {"type": "number", "default": 0.4},
        "hardware_ducking": {"type": "boolean", "default": False},
        "full_duplex": {"type": "boolean", "default": False},
        "noise_dbfs": {"type": "number", "default": -60},
    },
    "additionalProperties": False,
}

ROOMS: dict[str, AcousticRoom] = {}


class SimMic:
    sample_rate = SR

    def __init__(self, room: AcousticRoom) -> None:
        self.room = room

    async def stream(self) -> AsyncIterator[AudioChunk]:
        step = SR // 50
        t0 = time.monotonic()
        n = 0
        while True:
            t = t0 + n * step / SR
            delay = t + step / SR - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            yield AudioChunk(self.room.mic(t, step), SR)
            n += 1


class SimSpeaker:
    sample_rate = SR

    def __init__(self, room: AcousticRoom) -> None:
        self.room = room
        self.played_samples = 0

    async def write(self, chunk: AudioChunk) -> None:
        self.room.speaker_emit(time.monotonic(), chunk.pcm)
        self.played_samples += chunk.samples


class SimPtz:
    """Virtual PTZ: a 640x360 viewport moving over a larger panorama."""

    def __init__(self, camera: SimCamera) -> None:
        self.cam = camera
        self._caps = PtzCapabilities(pan=True, tilt=True, relative=True, absolute=True, presets=True,
                                     home=True, position_feedback=True, horizontal_fov_deg=60,
                                     vertical_fov_deg=34, pan_range_deg=180, tilt_range_deg=60)
        self.presets = {"home": (0.0, 0.0)}
        self.moves = 0

    @property
    def ptz_capabilities(self) -> PtzCapabilities:
        return self._caps

    async def move_relative(self, pan_fov: float, tilt_fov: float, zoom: float = 0.0) -> None:
        self.moves += 1
        await asyncio.sleep(0.3)  # mechanical movement
        self.cam.pan(pan_fov, tilt_fov)

    async def continuous_move(self, pan_speed: float, tilt_speed: float, zoom_speed: float = 0.0,
                              duration_s: float = 0.5) -> None:
        await self.move_relative(pan_speed * duration_s, tilt_speed * duration_s)

    async def stop(self) -> None:
        return None

    async def get_position(self) -> PtzPosition:
        return PtzPosition(pan=self.cam.cx, tilt=self.cam.cy)

    async def move_absolute(self, position: PtzPosition) -> None:
        self.cam.cx, self.cam.cy = position.pan, position.tilt
        self.cam.clamp()

    async def list_presets(self) -> list[PtzPreset]:
        return [PtzPreset(id=k, name=k) for k in self.presets]

    async def goto_preset(self, preset_id: str) -> None:
        self.cam.cx, self.cam.cy = self.presets[preset_id]

    async def save_preset(self, name: str) -> PtzPreset:
        self.presets[name] = (self.cam.cx, self.cam.cy)
        return PtzPreset(id=name, name=name)

    async def go_home(self) -> None:
        await self.goto_preset("home")


class SimCamera:
    W, H = 640, 360

    def __init__(self, image_path: str | None, ptz: bool) -> None:
        image = cv2.imread(image_path) if image_path and Path(image_path).exists() else None
        if image is None:
            image = np.full((720, 1920, 3), (90, 110, 120), np.uint8)
            cv2.putText(image, "JuStAI5 simulated camera", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (240, 240, 240), 3)
        self.panorama = image
        self.ptz = ptz
        # Viewport centre in [-1, 1] of the free travel range.
        self.cx = 0.0
        self.cy = 0.0
        h, w = image.shape[:2]
        scale = self.H / h if ptz else min(self.W / w, self.H / h)
        self.view_w = self.W / scale if ptz else w
        self.view_h = self.H / scale if ptz else h

    def clamp(self) -> None:
        self.cx = max(-1.0, min(1.0, self.cx))
        self.cy = max(-1.0, min(1.0, self.cy))

    def pan(self, pan_fov: float, tilt_fov: float) -> None:
        h, w = self.panorama.shape[:2]
        free_x = max(1.0, (w - self.view_w) / 2)
        free_y = max(1.0, (h - self.view_h) / 2)
        self.cx += pan_fov * self.view_w / free_x
        self.cy -= tilt_fov * self.view_h / free_y
        self.clamp()

    async def frame(self) -> np.ndarray:
        h, w = self.panorama.shape[:2]
        if not self.ptz:
            return cv2.resize(self.panorama, (self.W, int(self.W * h / w)))
        x0 = int((w - self.view_w) / 2 * (1 + self.cx))
        y0 = int((h - self.view_h) / 2 * (1 + self.cy))
        crop = self.panorama[y0:y0 + int(self.view_h), x0:x0 + int(self.view_w)]
        return cv2.resize(crop, (self.W, self.H))


class SimHandle(BaseDeviceHandle):
    def __init__(self, device_id: str, caps: set[str], room: AcousticRoom, camera: SimCamera | None,
                 ptz: SimPtz | None) -> None:
        super().__init__(device_id, caps)
        self.room, self.camera, self._ptz = room, camera, ptz
        self._mic = SimMic(room) if Capability.AUDIO_INPUT in caps else None
        self._speaker = SimSpeaker(room) if Capability.AUDIO_OUTPUT in caps else None

    def audio_source(self) -> SimMic | None:
        return self._mic

    def audio_sink(self) -> SimSpeaker | None:
        return self._speaker

    def video_source(self) -> SimCamera | None:
        return self.camera

    def ptz(self) -> SimPtz | None:
        return self._ptz

    async def snapshot(self) -> bytes | None:
        if self.camera is None:
            return None
        ok, buf = cv2.imencode(".jpg", await self.camera.frame())
        return buf.tobytes() if ok else None


class SimDriver:
    driver_id = "simulated"
    display_name = "Simuliertes Gerät"

    def config_schema(self) -> dict[str, Any]:
        return SCHEMA

    def secret_fields(self) -> list[str]:
        return []

    async def probe(self, config: dict[str, Any]) -> ProbeResult:
        caps: set[str] = set()
        if config.get("microphone", True):
            caps.add(Capability.AUDIO_INPUT)
        if config.get("speaker", True):
            caps.add(Capability.AUDIO_OUTPUT)
        if config.get("microphone", True) and config.get("speaker", True) and config.get("full_duplex"):
            caps.add(Capability.AUDIO_FULL_DUPLEX)
        if config.get("camera", True):
            caps |= {Capability.VIDEO_INPUT, Capability.CAMERA_SNAPSHOT}
            if config.get("ptz"):
                caps |= {Capability.PTZ_PAN, Capability.PTZ_TILT, Capability.PTZ_PRESETS,
                         Capability.PTZ_ABSOLUTE}
        return ProbeResult(ok=True, capabilities=sorted(caps),
                           info=DeviceInfo(manufacturer="JuStAI5", model="Simulator"))

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> SimHandle:
        room = AcousticRoom(AcousticParams(
            echo_delay_s=float(config.get("echo_delay_s", 0.8)), echo_gain=float(config.get("echo_gain", 0.4)),
            hardware_ducking=bool(config.get("hardware_ducking")), noise_dbfs=float(config.get("noise_dbfs", -60))))
        ROOMS[device_id] = room
        camera = SimCamera(config.get("image"), bool(config.get("ptz"))) if config.get("camera", True) else None
        ptz = SimPtz(camera) if camera is not None and config.get("ptz") else None
        return SimHandle(device_id, set(probe.capabilities), room, camera, ptz)


class SayParams(BaseModel):
    device_id: str
    text: str = Field(max_length=500)
    voice: str = Field("en_US-lessac-medium", description="Piper-Stimme des simulierten Benutzers")
    delay_s: float = Field(0.0, ge=0, le=60)


class SimulatedPlugin(Plugin):
    async def setup(self) -> None:
        self.ctx.register_provider("device_driver", SimDriver())
        self.ctx.register_tool(ToolDefinition(
            name="simulator.say",
            description="(Tests) Lässt einen simulierten Benutzer in das Mikrofon eines simulierten Geräts sprechen.",
            parameters=SayParams, category="testing", available_in_conversation=False, timeout_s=60), self.say)

    async def say(self, p: SayParams, ctx: ToolContext) -> ToolResult:
        room = ROOMS.get(p.device_id)
        if room is None:
            return ToolResult.failure("unknown_device", "kein simuliertes Gerät mit dieser ID aktiv")
        from piper import PiperVoice

        path = Path(os.environ.get("JUSTAI_MODELS_DIR", "/models")) / "piper" / f"{p.voice}.onnx"
        voice = await asyncio.to_thread(PiperVoice.load, str(path))
        pcm = np.concatenate([c.audio_int16_array for c in voice.synthesize(p.text)])
        import soxr

        pcm16 = soxr.resample(pcm, voice.config.sample_rate, SR).astype(np.int16)
        room.user_says(time.monotonic() + p.delay_s, pcm16)
        return ToolResult.success({"duration_s": round(pcm16.size / SR, 2)}, message="gesprochen")
