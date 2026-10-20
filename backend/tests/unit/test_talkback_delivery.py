"""The camera speaker route must be rebuilt when go2rtc stops delivering to the device."""

import asyncio

import numpy as np

from justai.audio.io import Go2rtcTalkbackSink, TalkbackRoutes


class FakeGo2rtc:
    def __init__(self, sources: dict[str, str] | None = None) -> None:
        self.plays = 0
        self.sent: int | None = None  # None = no route to the device
        self.sources = dict(sources or {})
        self.log: list[tuple[str, str]] = []

    def source(self, name: str) -> str | None:
        return self.sources.get(name)

    async def set_stream(self, name: str, sources: list[str]) -> None:
        self.sources[name] = sources[0]
        self.log.append(("set", name))

    async def delete_stream(self, name: str) -> None:
        self.sources.pop(name, None)
        self.log.append(("delete", name))

    async def play_live(self, name: str, url: str) -> None:
        self.plays += 1
        self.log.append(("play", name))

    async def stop_playback(self, name: str) -> None:
        return None

    async def backchannel_bytes(self, name: str) -> int | None:
        return self.sent


class FastSink(Go2rtcTalkbackSink):
    CHECK_INTERVAL_S = 0.02
    DELIVERY_TIMEOUT_S = 0.1
    CONNECT_TIMEOUT_S = 0.1


async def test_lost_route_is_rebuilt_and_speech_waits_until_delivered() -> None:
    go2rtc = FakeGo2rtc()
    sink = FastSink(go2rtc, "cam", TalkbackRoutes(), "http://core", settle_s=0.0)  # type: ignore[arg-type]
    await sink.open()
    st = sink.stats
    assert st is not None
    st.connected, st.first_pull = True, 1.0  # go2rtc pulls our stream ...
    frame = np.zeros(320, np.int16)
    for _ in range(15):  # ... but nothing reaches the camera
        await sink.write(frame)
        await asyncio.sleep(0.02)
    assert not sink.ready
    assert go2rtc.plays >= 2, "route was not rebuilt"

    go2rtc.sent = 0  # route works again: bytes start flowing to the device
    for i in range(10):
        go2rtc.sent += 160 * (i + 1)
        await asyncio.sleep(0.03)
    st = sink.stats
    assert st is not None
    st.connected, st.first_pull = True, 1.0
    assert sink.ready
    await sink.shutdown()


async def test_every_opening_uses_a_fresh_camera_connection_for_the_speaker() -> None:
    """A long-lived talk session can go silent on Tapo cameras (another client opened one):
    the speaker uses its own go2rtc stream, recreated on open and removed on close."""
    go2rtc = FakeGo2rtc({"cam": "tapo://secret@10.0.0.5?subtype=0"})
    sink = FastSink(go2rtc, "cam", TalkbackRoutes(), "http://core", settle_s=0.0)  # type: ignore[arg-type]
    await sink.open()
    assert go2rtc.log == [("delete", "cam_talk"), ("set", "cam_talk"), ("play", "cam_talk")]
    assert go2rtc.sources["cam_talk"] == go2rtc.sources["cam"]
    await sink.close()
    assert go2rtc.log[-1] == ("delete", "cam_talk") and "cam_talk" not in go2rtc.sources
    await sink.open()  # next conversation: new connection again
    assert go2rtc.log[-3:] == [("delete", "cam_talk"), ("set", "cam_talk"), ("play", "cam_talk")]
    await sink.shutdown()
    assert "cam_talk" not in go2rtc.sources


async def test_a_new_connection_gets_time_to_log_in_before_it_is_rebuilt() -> None:
    go2rtc = FakeGo2rtc({"cam": "tapo://secret@10.0.0.5?subtype=0"})

    class Sink(Go2rtcTalkbackSink):
        CHECK_INTERVAL_S = 0.02
        DELIVERY_TIMEOUT_S = 0.05
        CONNECT_TIMEOUT_S = 0.5

    sink = Sink(go2rtc, "cam", TalkbackRoutes(), "http://core", settle_s=0.0)  # type: ignore[arg-type]
    await sink.open()
    frame = np.zeros(320, np.int16)
    for _ in range(10):  # 0.2 s: still logging in (nothing pulled, nothing sent) - no rebuild
        await sink.write(frame)
        await asyncio.sleep(0.02)
    assert go2rtc.plays == 1
    go2rtc.sent = 0
    for i in range(5):  # connected: bytes flow
        go2rtc.sent += 160 * (i + 1)
        await asyncio.sleep(0.03)
    assert go2rtc.plays == 1
    await sink.shutdown()
