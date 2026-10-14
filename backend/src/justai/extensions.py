"""Feature modules built on top of the core services.

Each extension is an object with optional ``start()``/``stop()`` coroutines and an
optional ``register_tools(registry)``. They are constructed here so that the
container stays small and each feature could later move into its own process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from justai.automation.extension import AutomationExtension
from justai.display.extension import DisplayExtension
from justai.display.service import DisplayService
from justai.identity.service import IdentityService
from justai.memory.extension import MemoryExtension
from justai.memory.service import MemoryService
from justai.output.speech import SpeechService
from justai.ptz.extension import PtzExtension
from justai.ptz.service import PtzService
from justai.system.retention import RetentionService
from justai.vision.engine import VisionEngine
from justai.vision.extension import VisionExtension
from justai.vision.states import StateDetectors

if TYPE_CHECKING:
    from justai.container import Container


async def build_extensions(c: Container) -> dict[str, Any]:
    ext: dict[str, Any] = {}
    ext["speech"] = SpeechService(c.output, c.audio, c.ai)
    ext["memory"] = MemoryExtension(c, MemoryService(c.db, c.ai, c.bus))

    identity = IdentityService(c.db, c.bus)
    engine = VisionEngine(db=c.db, bus=c.bus, devices=c.devices, device_records=c.device_records,
                          rooms=c.rooms, providers=c.providers, go2rtc=c.go2rtc, identity=identity,
                          telemetry=c.telemetry, supervisor=c.supervisor)
    ext["vision"] = VisionExtension(c, engine, identity, StateDetectors(c.db, c.bus, engine))
    ext["ptz"] = PtzExtension(c, PtzService(c), identity)
    ext["display"] = DisplayExtension(c, DisplayService(c, c.components))
    ext["automation"] = AutomationExtension(c)
    ext["retention"] = RetentionService(c)

    from justai.devtools.extension import DevToolsExtension

    ext["devtools"] = DevToolsExtension(c)
    return ext
