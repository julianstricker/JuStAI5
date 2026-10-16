"""Device app cameras: MJPEG instead of go2rtc MP4, and the MJPEG stream itself."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from justai.display.media import mjpeg_frames
from justai.display.service import DisplayService


class _Devices:
    def __init__(self, runtimes: dict[str, Any]) -> None:
        self.runtimes = runtimes

    def get(self, device_id: str) -> Any:
        return self.runtimes.get(device_id)


def _service(runtimes: dict[str, Any]) -> DisplayService:
    c = SimpleNamespace(devices=_Devices(runtimes),
                        auth=SimpleNamespace(issue_scoped_token=lambda *a: "tok"))
    return DisplayService(c, components=None)  # type: ignore[arg-type]


def _src(service: DisplayService, device_id: str) -> str:
    doc = {"components": [{"type": "row", "children": [{"type": "camera", "device_id": device_id}]}]}
    out = service._inject_media_urls(doc, frozenset({"camera.read"}), system=False)
    return str(out["components"][0]["children"][0]["src"])


def test_camera_with_go2rtc_stream_is_mp4_and_app_camera_is_mjpeg() -> None:
    service = _service({
        "tapo": SimpleNamespace(stream="cam_tapo", sub_stream="cam_tapo_sub"),
        "phone": SimpleNamespace(stream=None, sub_stream=None),
    })
    assert _src(service, "tapo") == "/api/display/camera/tapo.mp4?token=tok"
    assert _src(service, "phone") == "/api/display/camera/phone.mjpeg?token=tok"


def test_mjpeg_stream_sends_only_new_frames_and_survives_errors() -> None:
    frames = iter([None, b"\xff\xd8a", b"\xff\xd8a", RuntimeError("gone"), b"\xff\xd8b"])

    async def snapshot() -> bytes | None:
        item = next(frames)
        if isinstance(item, Exception):
            raise item
        return item

    async def collect() -> list[bytes]:
        out = []
        async for part in mjpeg_frames(snapshot, interval_s=0):
            out.append(part)
            if len(out) == 2:
                break
        return out

    parts = asyncio.run(collect())
    assert [p.split(b"\r\n\r\n", 1)[1] for p in parts] == [b"\xff\xd8a\r\n", b"\xff\xd8b\r\n"]
    assert all(p.startswith(b"--frame\r\nContent-Type: image/jpeg") for p in parts)
