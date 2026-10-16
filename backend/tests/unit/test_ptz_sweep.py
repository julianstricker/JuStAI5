"""Room sweep: systematic views over the whole pan range and two heights."""

from types import SimpleNamespace

from justai_sdk.ports.ptz import PtzPreset

from justai.ptz.service import SWEEP_PAN, SWEEP_TILT, PtzService


class FakePtz:
    def __init__(self, presets: list[PtzPreset] | None = None) -> None:
        self.position = [0.0, 0.0]
        self.presets = presets or [PtzPreset(id="1", name="home")]
        self.visited_presets: list[str] = []
        self.ptz_capabilities = SimpleNamespace(presets=True)

    async def move_relative(self, pan: float, tilt: float, zoom: float = 0.0) -> None:
        self.position = [round(self.position[0] + pan, 3), round(self.position[1] + tilt, 3)]

    async def go_home(self) -> None:
        self.position = [0.0, 0.0]

    async def list_presets(self) -> list[PtzPreset]:
        return self.presets

    async def goto_preset(self, preset_id: str) -> None:
        self.visited_presets.append(preset_id)


def service(ptz: FakePtz) -> PtzService:
    runtime = SimpleNamespace(name="cam", settings={}, handle=SimpleNamespace(ptz=lambda: ptz))
    devices = SimpleNamespace(require=lambda _id: runtime, get=lambda _id: runtime)
    return PtzService(SimpleNamespace(devices=devices))  # type: ignore[arg-type]


async def test_sweep_covers_all_directions_in_a_snake_path_with_only_a_home_preset() -> None:
    ptz = FakePtz()
    svc = service(ptz)
    seen: list[tuple[str, list[float]]] = []

    async def capture(label: str) -> None:
        seen.append((label, list(ptz.position)))

    views = await svc.sweep("cam", capture, settle_s=0)
    assert len(views) == len(SWEEP_PAN) * len(SWEEP_TILT) == len(seen)
    assert [pos for _, pos in seen[:5]] == [[p, 0.0] for p in SWEEP_PAN]
    assert [pos for _, pos in seen[5:]] == [[p, SWEEP_TILT[1]] for p in reversed(SWEEP_PAN)]
    assert seen[0][0] == "ganz links" and seen[-1][0] == "ganz links, unten"

    await svc.goto_view("cam", views[3])  # back to the view where something was found
    assert ptz.position == [SWEEP_PAN[3], 0.0]


async def test_sweep_uses_own_viewpoints_when_three_presets_exist() -> None:
    ptz = FakePtz([PtzPreset(id="1", name="home"), PtzPreset(id="2", name="Tür"),
                   PtzPreset(id="3", name="Sofa"), PtzPreset(id="4", name="Tisch")])
    labels: list[str] = []

    async def capture(label: str) -> None:
        labels.append(label)

    await service(ptz).sweep("cam", capture, settle_s=0)
    assert labels == ["Tür", "Sofa", "Tisch"] and ptz.visited_presets == ["2", "3", "4"]
