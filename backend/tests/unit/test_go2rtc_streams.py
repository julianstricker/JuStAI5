"""go2rtc keeps streams only in memory: after a restart the core must restore them."""

import httpx

from justai.media.go2rtc import Go2rtcClient


class FakeGo2rtc:
    def __init__(self) -> None:
        self.streams: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/streams" and request.method == "PATCH":
            self.streams[request.url.params["name"]] = request.url.params["src"]
            return httpx.Response(200)
        if request.url.path == "/api/streams" and request.method == "GET":
            return httpx.Response(200, json={k: {"producers": []} for k in self.streams})
        if request.url.path == "/api/streams" and request.method == "DELETE":
            self.streams.pop(request.url.params["src"], None)
            return httpx.Response(200)
        return httpx.Response(404)


def client(fake: FakeGo2rtc) -> Go2rtcClient:
    c = Go2rtcClient("http://go2rtc:1984", "rtsp://go2rtc:8554")
    c._http = httpx.AsyncClient(base_url=c.base_url, transport=httpx.MockTransport(fake.handler))
    return c


async def test_lost_streams_are_restored_and_deleted_ones_stay_deleted() -> None:
    fake = FakeGo2rtc()
    c = client(fake)
    await c.set_stream("cam1", ["tapo://secret@192.168.0.2"])
    await c.set_stream("cam2", ["rtsp://192.168.0.3/stream1"])
    await c.delete_stream("cam2")
    assert await c.ensure_streams() == []

    fake.streams.clear()  # go2rtc restarted
    assert await c.ensure_streams() == ["cam1"]
    assert fake.streams == {"cam1": "tapo://secret@192.168.0.2"}
    assert c.restored == 1
