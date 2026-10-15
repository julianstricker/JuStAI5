"""The camera speaker route must be rebuilt when go2rtc stops delivering to the device."""

import asyncio

import numpy as np

from justai.audio.io import Go2rtcTalkbackSink, TalkbackRoutes


class FakeGo2rtc:
    def __init__(self) -> None:
        self.plays = 0
        self.sent: int | None = None  # None = no route to the device

    async def play_live(self, name: str, url: str) -> None:
        self.plays += 1

    async def stop_playback(self, name: str) -> None:
        return None

    async def backchannel_bytes(self, name: str) -> int | None:
        return self.sent


class FastSink(Go2rtcTalkbackSink):
    CHECK_INTERVAL_S = 0.02
    DELIVERY_TIMEOUT_S = 0.1


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
