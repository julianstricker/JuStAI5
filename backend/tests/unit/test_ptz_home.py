"""Home on cameras without a native home position (Tapo)."""

from types import SimpleNamespace

import pytest
from justai_sdk.ports.ptz import PtzPreset

from justai.common.errors import Conflict
from justai.ptz.service import PtzService


class FakePtz:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.presets: list[PtzPreset] = []

    async def move_relative(self, pan: float, tilt: float, zoom: float = 0.0) -> None:
        self.moves.append((round(pan, 3), round(tilt, 3)))

    async def go_home(self) -> None:
        home = next((p for p in self.presets if p.name == "home"), None)
        if home is None:
            raise NotImplementedError("no preset named 'home'")
        self.moves.append(("preset", home.id))  # type: ignore[arg-type]

    async def list_presets(self) -> list[PtzPreset]:
        return list(self.presets)

    async def delete_preset(self, preset_id: str) -> None:
        self.presets = [p for p in self.presets if p.id != preset_id]

    async def save_preset(self, name: str) -> PtzPreset:
        preset = PtzPreset(id=str(len(self.presets) + 1), name=name)
        self.presets.append(preset)
        return preset


def service(ptz: FakePtz) -> PtzService:
    runtime = SimpleNamespace(name="cam", settings={}, handle=SimpleNamespace(ptz=lambda: ptz))
    devices = SimpleNamespace(require=lambda _id: runtime, get=lambda _id: runtime)
    return PtzService(SimpleNamespace(devices=devices))  # type: ignore[arg-type]


async def test_home_without_position_explains_instead_of_crashing() -> None:
    with pytest.raises(Conflict, match="Als Home speichern"):
        await service(FakePtz()).home("cam")


async def test_home_without_preset_undoes_own_movements() -> None:
    ptz = FakePtz()
    svc = service(ptz)
    await svc.move("cam", 0.2, 0.0)
    await svc.move("cam", 0.1, -0.05)
    await svc.home("cam")
    assert ptz.moves[-1] == (-0.3, 0.05)


async def test_set_home_replaces_existing_home_preset() -> None:
    ptz = FakePtz()
    svc = service(ptz)
    await svc.set_home("cam")
    await svc.set_home("cam")
    assert [p.name for p in ptz.presets] == ["home"]
    await svc.move("cam", 0.2, 0.0)
    await svc.home("cam")
    assert ptz.moves[-1] == ("preset", ptz.presets[0].id)
