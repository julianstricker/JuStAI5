from dataclasses import dataclass, field

import pytest

from justai.common.errors import RoutingDenied
from justai.output.router import (
    OutputKind,
    OutputRequest,
    OutputRouter,
    TopoDevice,
    TopoEndpoint,
    TopoRoom,
)

AUDIO = frozenset({"audio.output"})
DISPLAY = frozenset({"display.text", "display.dashboard"})


@dataclass
class FakeTopology:
    rooms: dict[str, TopoRoom] = field(default_factory=dict)
    endpoints: dict[str, TopoEndpoint] = field(default_factory=dict)
    devices: dict[str, TopoDevice] = field(default_factory=dict)

    def endpoint(self, endpoint_id):
        return self.endpoints.get(endpoint_id)

    def room(self, room_id):
        return self.rooms.get(room_id)

    def endpoints_in_room(self, room_id):
        return [e for e in self.endpoints.values() if e.room_id == room_id]

    def devices_in_room(self, room_id):
        return [d for d in self.devices.values() if d.room_id == room_id]

    def device(self, device_id):
        return self.devices.get(device_id)


@pytest.fixture
def topo() -> FakeTopology:
    t = FakeTopology()
    t.rooms = {
        "living": TopoRoom("living", "Wohnzimmer"),
        "kitchen": TopoRoom("kitchen", "Küche"),
        "bedroom": TopoRoom("bedroom", "Schlafzimmer", announcements_allowed=False),
    }
    t.devices = {
        "cam-living": TopoDevice("cam-living", "C200", "living", AUDIO | {"audio.input"}, True),
        "spk-living2": TopoDevice("spk-living2", "Sonos", "living", AUDIO, True),
        "tv-living": TopoDevice("tv-living", "TV", "living", DISPLAY, True),
        "spk-kitchen": TopoDevice("spk-kitchen", "Küchenlautsprecher", "kitchen", AUDIO, True),
        "tv-kitchen": TopoDevice("tv-kitchen", "Küchen-Tablet", "kitchen", DISPLAY, True),
        "spk-bed": TopoDevice("spk-bed", "Bett", "bedroom", AUDIO, True),
    }
    t.endpoints = {
        "ep-living": TopoEndpoint("ep-living", "living", "cam-living", ("tv-living",)),
        "ep-kitchen": TopoEndpoint("ep-kitchen", "kitchen", "spk-kitchen", ()),
    }
    return t


def test_audio_goes_to_originating_endpoint_speaker(topo: FakeTopology) -> None:
    d = OutputRouter(topo).route(OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living"))
    assert d.device_ids == ("cam-living",)
    assert d.room_id == "living"
    assert not d.cross_room


def test_endpoint_room_wins_over_claimed_room(topo: FakeTopology) -> None:
    # Even if some component (or the LLM) claims "kitchen", the endpoint decides.
    d = OutputRouter(topo).route(
        OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living", origin_room_id="kitchen")
    )
    assert d.room_id == "living"
    assert d.device_ids == ("cam-living",)


def test_cross_room_without_explicit_flag_is_denied(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied):
        OutputRouter(topo).route(
            OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living", target_room_id="kitchen",
                          permissions=frozenset({"output.cross_room"}))
        )


def test_cross_room_needs_permission(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied, match=r"output\.cross_room"):
        OutputRouter(topo).route(
            OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living", target_room_id="kitchen",
                          explicit_cross_room=True)
        )


def test_explicit_announcement_to_kitchen(topo: FakeTopology) -> None:
    d = OutputRouter(topo).route(
        OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living", target_room_id="kitchen",
                      explicit_cross_room=True, permissions=frozenset({"output.cross_room"}))
    )
    assert d.device_ids == ("spk-kitchen",)
    assert d.cross_room


def test_room_refusing_announcements(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied, match="announcements"):
        OutputRouter(topo).route(
            OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living", target_room_id="bedroom",
                          explicit_cross_room=True, permissions=frozenset({"output.cross_room"}))
        )


def test_failed_speaker_falls_back_within_same_room_only(topo: FakeTopology) -> None:
    topo.devices["cam-living"] = TopoDevice("cam-living", "C200", "living", AUDIO, online=False)
    d = OutputRouter(topo).route(OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living"))
    assert d.device_ids == ("spk-living2",)


def test_no_speaker_in_room_fails_instead_of_using_other_room(topo: FakeTopology) -> None:
    topo.devices["cam-living"] = TopoDevice("cam-living", "C200", "living", AUDIO, online=False)
    topo.devices["spk-living2"] = TopoDevice("spk-living2", "Sonos", "living", AUDIO, online=False)
    with pytest.raises(RoutingDenied, match="no available audio"):
        OutputRouter(topo).route(OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living"))


def test_explicit_device_in_other_room_is_rejected(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied, match="not in the target room"):
        OutputRouter(topo).route(
            OutputRequest(OutputKind.AUDIO, origin_endpoint_id="ep-living",
                          target_device_id="spk-kitchen")
        )


def test_display_prefers_endpoint_display(topo: FakeTopology) -> None:
    d = OutputRouter(topo).route(
        OutputRequest(OutputKind.DISPLAY, origin_endpoint_id="ep-living",
                      required_capabilities=frozenset({"display.dashboard"}))
    )
    assert d.device_ids == ("tv-living",)


def test_display_from_room_without_endpoint_display(topo: FakeTopology) -> None:
    d = OutputRouter(topo).route(OutputRequest(OutputKind.DISPLAY, origin_endpoint_id="ep-kitchen"))
    assert d.device_ids == ("tv-kitchen",)


def test_personal_content_blocked_on_shared_display(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied) as exc:
        OutputRouter(topo).route(
            OutputRequest(OutputKind.DISPLAY, origin_endpoint_id="ep-living", personal_content=True)
        )
    assert exc.value.code == "private_content_on_shared_display"


def test_display_missing_capability(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied):
        OutputRouter(topo).route(
            OutputRequest(OutputKind.DISPLAY, origin_endpoint_id="ep-living",
                          required_capabilities=frozenset({"display.video"}))
        )


def test_output_without_origin_requires_admin(topo: FakeTopology) -> None:
    with pytest.raises(RoutingDenied):
        OutputRouter(topo).route(OutputRequest(OutputKind.AUDIO, target_room_id="kitchen"))
    d = OutputRouter(topo).route(OutputRequest(OutputKind.AUDIO, target_room_id="kitchen", admin=True))
    assert d.device_ids == ("spk-kitchen",)
