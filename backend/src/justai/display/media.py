"""Audio/video of the browser device app (phone, tablet, PC) over its WebSocket.

Binary messages carry one type byte followed by the payload:

* ``0x01`` client -> core: microphone, PCM16 little-endian, mono, 16 kHz (20 ms frames)
* ``0x02`` client -> core: camera frame, JPEG
* ``0x11`` core -> client: speaker, PCM16 little-endian, mono, 16 kHz

The device then is an ordinary JuStAI5 device: its microphone feeds wakeword and
conversations, its camera vision and face recognition, its speaker the Output Router.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

import cv2
import numpy as np
from justai_sdk.audio import AudioChunk

if TYPE_CHECKING:
    from justai.display.service import DisplayService

MIC = 0x01
CAMERA = 0x02
SPEAKER = 0x11
SAMPLE_RATE = 16000
FRAME_MAX_AGE_S = 10.0
MAX_JPEG_BYTES = 2_000_000

# What a browser device may announce (everything else is ignored).
ALLOWED_CAPABILITIES = ("display.", "audio.input", "audio.output", "video.input", "camera.snapshot")


def allowed_capabilities(caps: list[object]) -> list[str]:
    return sorted({str(c) for c in caps if any(str(c) == a or (a.endswith(".") and str(c).startswith(a))
                                                for a in ALLOWED_CAPABILITIES)})


class DeviceMedia:
    """Media state of one paired device; survives reconnects of its WebSocket."""

    def __init__(self) -> None:
        self.mic: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=100)  # 2 s of 20 ms frames
        self.jpeg: bytes | None = None
        self.jpeg_at = 0.0
        self.mic_frames = 0
        self.camera_frames = 0

    def on_binary(self, data: bytes) -> None:
        if not data:
            return
        kind, payload = data[0], data[1:]
        if kind == MIC and payload and len(payload) % 2 == 0:
            pcm = np.frombuffer(payload, "<i2").astype(np.int16)
            if self.mic.full():  # consumer too slow: drop the oldest frame, keep real time
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.mic.get_nowait()
            self.mic.put_nowait(pcm)
            self.mic_frames += 1
        elif kind == CAMERA and payload[:2] == b"\xff\xd8" and len(payload) <= MAX_JPEG_BYTES:
            self.jpeg, self.jpeg_at = bytes(payload), time.monotonic()
            self.camera_frames += 1

    def reset_mic(self) -> None:
        while not self.mic.empty():
            self.mic.get_nowait()

    def fresh_jpeg(self) -> bytes | None:
        if self.jpeg is not None and time.monotonic() - self.jpeg_at <= FRAME_MAX_AGE_S:
            return self.jpeg
        return None


class BrowserMicSource:
    sample_rate = SAMPLE_RATE

    def __init__(self, media: DeviceMedia) -> None:
        self.media = media

    async def stream(self) -> AsyncIterator[AudioChunk]:
        while True:
            yield AudioChunk(await self.media.mic.get(), SAMPLE_RATE)


class BrowserSpeakerSink:
    sample_rate = SAMPLE_RATE

    def __init__(self, service: DisplayService, device_id: str) -> None:
        self.service = service
        self.device_id = device_id

    async def write(self, chunk: AudioChunk) -> None:
        conn = self.service.connections.get(self.device_id)
        if conn is None:
            return
        payload = np.asarray(chunk.pcm, np.int16).astype("<i2").tobytes()
        with contextlib.suppress(Exception):
            await conn.ws.send_bytes(bytes([SPEAKER]) + payload)


class BrowserCamera:
    def __init__(self, media: DeviceMedia) -> None:
        self.media = media

    async def frame(self) -> np.ndarray | None:
        jpeg = self.media.fresh_jpeg()
        if jpeg is None:
            return None
        image = await asyncio.to_thread(cv2.imdecode, np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        return image if image is not None else None


MJPEG_MEDIA_TYPE = "multipart/x-mixed-replace; boundary=frame"


async def mjpeg_frames(snapshot: Callable[[], Awaitable[bytes | None]],
                       interval_s: float = 0.2) -> AsyncIterator[bytes]:
    """Live view for cameras without a go2rtc stream (device app): new frames as MJPEG parts."""
    last: bytes | None = None
    while True:
        with contextlib.suppress(Exception):
            jpeg = await snapshot()
            if jpeg and jpeg != last:
                last = jpeg
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        await asyncio.sleep(interval_s)
