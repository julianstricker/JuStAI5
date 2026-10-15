"""Frame sources for analysis (low resolution, low frame rate)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Protocol, cast

import cv2
import numpy as np
from justai_sdk.ports.devices import VideoSource
from justai_sdk.ports.vision import Image

from justai.logging import get_logger

log = get_logger(__name__)


class FrameSource(Protocol):
    def frames(self) -> AsyncIterator[tuple[float, Image]]: ...


async def probe_size(rtsp_url: str) -> tuple[int, int]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", rtsp_url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
    streams = json.loads(out or b"{}").get("streams") or []
    if not streams:
        raise ConnectionError("no video stream")
    return int(streams[0]["width"]), int(streams[0]["height"])


class FfmpegFrameSource:
    """Decodes a go2rtc RTSP stream to BGR frames at ``fps`` and ``width``."""

    def __init__(self, rtsp_url: str, fps: float, width: int = 640) -> None:
        self.rtsp_url = rtsp_url
        self.fps = fps
        self.width = width

    async def frames(self) -> AsyncIterator[tuple[float, Image]]:
        src_w, src_h = await probe_size(self.rtsp_url)
        w = min(self.width, src_w)
        h = int(round(src_h * w / src_w / 2)) * 2
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport", "tcp",
            "-i", self.rtsp_url, "-an", "-vf", f"fps={self.fps},scale={w}:{h}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        size = w * h * 3
        assert proc.stdout is not None
        try:
            while True:
                data = await asyncio.wait_for(proc.stdout.readexactly(size), timeout=30)
                yield time.monotonic(), np.frombuffer(data, np.uint8).reshape(h, w, 3)
        except asyncio.IncompleteReadError:
            return
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


class DeviceFrameSource:
    """Polls a plugin-provided camera."""

    def __init__(self, source: VideoSource, fps: float, width: int = 640) -> None:
        self.source = source
        self.fps = fps
        self.width = width

    async def frames(self) -> AsyncIterator[tuple[float, Image]]:
        interval = 1.0 / self.fps
        while True:
            started = time.monotonic()
            frame = await self.source.frame()
            if frame is not None:
                if frame.shape[1] > self.width:
                    scale = self.width / frame.shape[1]
                    frame = cv2.resize(frame, (self.width, int(frame.shape[0] * scale)))
                yield time.monotonic(), cast(Image, frame)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


def apply_privacy_mask(image: Image, zones: list[list[tuple[float, float]]]) -> Image:
    """Black out privacy zones (normalised polygons) before any analysis."""
    if not zones:
        return image
    h, w = image.shape[:2]
    masked = image.copy()
    for poly in zones:
        pts = np.array([[int(x * w), int(y * h)] for x, y in poly], dtype=np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(masked, [pts], (0, 0, 0))
    return masked


class MotionDetector:
    """Running-average background difference on a small grayscale image."""

    def __init__(self, threshold: float = 0.004, quiet_s: float = 3.0) -> None:
        self.threshold = threshold
        self.quiet_s = quiet_s
        self._bg: np.ndarray | None = None
        self.active = False
        self.score = 0.0
        self._last_motion = 0.0

    def update(self, image: np.ndarray, t: float) -> bool | None:
        """Returns True on motion start, False on motion end, None otherwise."""
        small = cv2.resize(image, (160, max(1, int(image.shape[0] * 160 / image.shape[1]))))
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if self._bg is None or self._bg.shape != gray.shape:
            self._bg = gray
            return None
        diff = cv2.absdiff(gray, self._bg)
        cv2.accumulateWeighted(gray, self._bg, 0.3)
        self.score = float((diff > 25).mean())
        if self.score > self.threshold:
            self._last_motion = t
            if not self.active:
                self.active = True
                return True
        elif self.active and t - self._last_motion > self.quiet_s:
            self.active = False
            return False
        return None
