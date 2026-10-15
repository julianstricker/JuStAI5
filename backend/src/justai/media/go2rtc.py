"""Client for the go2rtc media server.

go2rtc relays all network camera streams. JuStAI registers streams dynamically
(one per device, ``dev_<id>``) so device configuration lives in the JuStAI
database and not in go2rtc.yaml. Credentials are therefore only kept in memory by
go2rtc and are never written to its config file.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from justai.common.errors import Unavailable
from justai.common.redact import redact_text
from justai.logging import get_logger

log = get_logger(__name__)


def stream_name(device_id: str, sub: bool = False) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in device_id)
    return f"{safe}_sub" if sub else safe


class Go2rtcClient:
    def __init__(self, base_url: str, rtsp_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.rtsp_url = rtsp_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        # Streams this core registered. go2rtc keeps them only in memory, so after a
        # go2rtc restart they are gone; ``keep_streams`` restores them.
        self._desired: dict[str, str] = {}
        self.restored = 0

    async def close(self) -> None:
        await self._http.aclose()

    async def healthy(self) -> bool:
        try:
            r = await self._http.get("/api")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def info(self) -> dict[str, Any]:
        r = await self._http.get("/api")
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    async def set_stream(self, name: str, sources: list[str]) -> None:
        """Create or replace a stream (in memory only).

        ``PATCH`` is used on purpose: go2rtc's ``PUT`` also writes the stream - with
        its credentials - into go2rtc.yaml. ``PATCH`` accepts one source per stream.
        """
        if not sources:
            raise ValueError("stream needs a source")
        if len(sources) > 1:
            log.warning("go2rtc stream uses only the first source", stream=name)
        try:
            r = await self._http.patch("/api/streams", params={"name": name, "src": sources[0]})
        except httpx.HTTPError as exc:
            raise Unavailable(f"go2rtc unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise Unavailable(f"go2rtc rejected stream {name}: {redact_text(r.text)[:200]}")
        self._desired[name] = sources[0]

    async def delete_stream(self, name: str) -> None:
        self._desired.pop(name, None)
        try:
            await self._http.delete("/api/streams", params={"src": name})
        except httpx.HTTPError as exc:
            log.warning("go2rtc delete failed", stream=name, error=str(exc))

    async def ensure_streams(self) -> list[str]:
        """Re-register streams that go2rtc lost (e.g. after a restart). Returns their names."""
        missing = sorted(set(self._desired) - set(await self.streams()))
        for name in missing:
            src = self._desired.get(name)
            if src is not None:
                await self.set_stream(name, [src])
        if missing:
            self.restored += len(missing)
            log.warning("go2rtc lost streams, restored", streams=missing)
        return missing

    async def keep_streams(self, interval_s: float = 5.0) -> None:
        """Watchdog loop (run under the supervisor)."""
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.ensure_streams()
            except (httpx.HTTPError, Unavailable) as exc:
                log.debug("go2rtc not reachable for stream check", error=str(exc))

    async def streams(self) -> dict[str, Any]:
        r = await self._http.get("/api/streams")
        r.raise_for_status()
        data: dict[str, Any] = r.json() or {}
        return data

    async def stream_info(self, name: str) -> dict[str, Any] | None:
        r = await self._http.get("/api/streams", params={"src": name})
        if r.status_code != 200:
            return None
        data: dict[str, Any] = r.json()
        return data

    async def probe_medias(self, name: str, timeout_s: float = 15.0) -> list[str]:
        """Connect the producer (via a temporary consumer) and return its media list,
        e.g. ``["video, recvonly, H264", "audio, recvonly, PCMA/8000",
        "audio, sendonly, PCMA/8000"]``. The producer only exists while consumed."""
        import contextlib

        async def consume() -> None:
            async with self._http.stream("GET", "/api/stream.mp4", params={"src": name},
                                         timeout=timeout_s + 5) as r:
                async for _ in r.aiter_raw():
                    pass

        consumer = asyncio.create_task(consume())
        try:
            deadline = asyncio.get_running_loop().time() + timeout_s
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.5)
                info = await self.stream_info(name)
                medias = [m for p in (info or {}).get("producers") or []
                          for m in p.get("medias") or [] if isinstance(m, str)]
                if medias:
                    return medias
                if consumer.done():
                    break
            return []
        finally:
            consumer.cancel()
            with contextlib.suppress(BaseException):
                await consumer

    async def snapshot(self, name: str, width: int | None = None) -> bytes:
        params: dict[str, Any] = {"src": name}
        if width:
            params["width"] = width
        try:
            r = await self._http.get("/api/frame.jpeg", params=params, timeout=15.0)
        except httpx.HTTPError as exc:
            raise Unavailable(f"snapshot failed: {exc}") from exc
        if r.status_code != 200 or not r.content:
            raise Unavailable(f"snapshot failed ({r.status_code})")
        return r.content

    async def play_live(self, name: str, live_url: str) -> None:
        """Make go2rtc pull an endless audio stream and send it to the device backchannel."""
        r = await self._http.post("/api/ffmpeg", params={"dst": name, "live": live_url})
        if r.status_code >= 400:
            raise Unavailable(f"go2rtc talkback failed: {redact_text(r.text)[:200]}")

    async def backchannel_bytes(self, name: str) -> int | None:
        """Bytes go2rtc has sent to the device speaker of this stream (None: no route)."""
        info = await self.stream_info(name)
        senders = [s for p in (info or {}).get("producers") or [] for s in p.get("senders") or []]
        if not senders:
            return None
        return sum(int(s.get("bytes") or 0) for s in senders)

    async def stop_playback(self, name: str) -> None:
        """Remove the talkback producer (flushes go2rtc-side buffers)."""
        await self._http.post("/api/streams", params={"dst": name, "src": ""})

    def rtsp(self, name: str, *, audio_only: bool = False, video_only: bool = False) -> str:
        query = "?audio" if audio_only else "?video" if video_only else ""
        return f"{self.rtsp_url}/{name}{query}"

    @staticmethod
    def backchannel_active(info: dict[str, Any] | None) -> bool:
        if not info:
            return False
        for producer in info.get("producers") or []:
            for media in producer.get("medias") or []:
                if isinstance(media, str) and media.startswith("audio, sendonly"):
                    return True
        return False
