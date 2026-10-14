"""Device runtime: probing, connecting, health monitoring.

Every enabled device runs in its own supervised task. A device that fails is
retried with backoff and marked offline; this never affects other devices or rooms
(acceptance criterion 20).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from justai_sdk.events import Event, EventSource
from justai_sdk.ports.devices import Capability, DeviceDriver, DeviceHandle, ProbeResult

from justai.common.errors import NotFound, Unavailable
from justai.common.supervisor import Supervisor
from justai.db.models import Device
from justai.devices.service import DeviceService
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.media.go2rtc import Go2rtcClient, stream_name
from justai.plugins.providers import ProviderRegistry

log = get_logger(__name__)

ReadyListener = Callable[["DeviceRuntime", bool], Awaitable[None]]


@dataclass
class DeviceRuntime:
    device_id: str
    name: str
    driver_id: str
    room_id: str | None
    settings: dict[str, object]
    handle: DeviceHandle | None = None
    probe: ProbeResult | None = None
    status: str = "connecting"
    detail: str | None = None
    stream: str | None = None  # go2rtc main stream name
    sub_stream: str | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def capabilities(self) -> set[str]:
        if self.handle is not None:
            return self.handle.capabilities
        return set(self.probe.capabilities) if self.probe else set()

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def online(self) -> bool:
        return self.status == "online"


class DeviceManager:
    HEALTH_INTERVAL_S = 30.0

    def __init__(
        self,
        devices: DeviceService,
        providers: ProviderRegistry,
        go2rtc: Go2rtcClient,
        bus: EventBus,
        supervisor: Supervisor,
    ) -> None:
        self.devices = devices
        self.providers = providers
        self.go2rtc = go2rtc
        self.bus = bus
        self.supervisor = supervisor
        self._runtimes: dict[str, DeviceRuntime] = {}
        self._listeners: list[ReadyListener] = []

    # ----------------------------------------------------------------- lifecycle
    def on_ready_change(self, listener: ReadyListener) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        for device in await self.devices.list():
            if device.enabled:
                await self.activate(device)
            else:
                await self.devices.set_status(device.id, status="disabled")

    async def stop(self) -> None:
        for device_id in list(self._runtimes):
            await self.deactivate(device_id)

    async def activate(self, device: Device) -> None:
        await self.deactivate(device.id)
        runtime = DeviceRuntime(device.id, device.name, device.driver_id, device.room_id,
                                dict(device.settings or {}))
        self._runtimes[device.id] = runtime
        self.supervisor.start(f"device:{device.id}", lambda: self._run(runtime),
                              max_backoff_s=120)

    async def deactivate(self, device_id: str) -> None:
        await self.supervisor.stop(f"device:{device_id}")
        runtime = self._runtimes.pop(device_id, None)
        if runtime is not None:
            await self._teardown(runtime)

    async def reload(self, device_id: str) -> None:
        device = await self.devices.get(device_id)
        if device.enabled:
            await self.activate(device)
        else:
            await self.deactivate(device_id)
            await self.devices.set_status(device_id, status="disabled")

    async def on_driver_change(self, driver_id: str, available: bool) -> None:
        """(Re)activate devices when their driver plugin is enabled or disabled."""
        for device in await self.devices.list():
            if device.driver_id == driver_id and device.enabled:
                if available:
                    await self.activate(device)
                else:
                    await self.deactivate(device.id)
                    await self.devices.set_status(device.id, status="no_driver",
                                                  detail=f"driver {driver_id} not available")

    # -------------------------------------------------------------------- access
    def get(self, device_id: str) -> DeviceRuntime | None:
        return self._runtimes.get(device_id)

    def require(self, device_id: str) -> DeviceRuntime:
        runtime = self._runtimes.get(device_id)
        if runtime is None:
            raise NotFound(f"device {device_id} is not active")
        if not runtime.online or runtime.handle is None:
            raise Unavailable(f"device {runtime.name} is {runtime.status}")
        return runtime

    def runtimes(self) -> list[DeviceRuntime]:
        return list(self._runtimes.values())

    def driver(self, driver_id: str) -> DeviceDriver | None:
        driver = self.providers.get("device_driver", driver_id)
        return driver  # type: ignore[no-any-return]

    async def probe(self, driver_id: str, config: dict[str, object]) -> ProbeResult:
        driver = self.driver(driver_id)
        if driver is None:
            raise NotFound(f"driver {driver_id} not available")
        return await driver.probe(config)

    async def snapshot(self, device_id: str, width: int | None = 1280) -> bytes:
        runtime = self.require(device_id)
        assert runtime.handle is not None
        if Capability.CAMERA_SNAPSHOT not in runtime.capabilities and \
                Capability.VIDEO_INPUT not in runtime.capabilities:
            raise Unavailable(f"{runtime.name} has no camera")
        data = await runtime.handle.snapshot()
        if data:
            return data
        if runtime.stream:
            return await self.go2rtc.snapshot(runtime.stream, width=width)
        raise Unavailable(f"{runtime.name} cannot provide snapshots")

    # ------------------------------------------------------------------ internals
    async def _run(self, runtime: DeviceRuntime) -> None:
        device = await self.devices.get(runtime.device_id)
        driver = self.driver(device.driver_id)
        if driver is None:
            await self._set_status(runtime, "no_driver", f"driver {device.driver_id} not available")
            # Wait for the plugin; on_driver_change re-activates the device.
            await asyncio.Event().wait()
            return
        config = await self.devices.full_config(device)
        try:
            probe = await asyncio.wait_for(driver.probe(config), timeout=30)
        except TimeoutError as exc:
            await self._set_status(runtime, "offline", "probe timed out")
            raise Unavailable("probe timeout") from exc
        runtime.probe = probe
        if not probe.ok:
            await self._set_status(runtime, "offline", probe.error or "probe failed")
            raise Unavailable(probe.error or "probe failed")

        handle = await driver.open(device.id, config, probe)
        runtime.handle = handle
        media = handle.media()
        if media is not None:
            runtime.stream = stream_name(device.id)
            await self.go2rtc.set_stream(runtime.stream, media.sources)
            if media.sub_sources:
                runtime.sub_stream = stream_name(device.id, sub=True)
                await self.go2rtc.set_stream(runtime.sub_stream, media.sub_sources)
        await self.devices.set_status(device.id, status="online", detail=None,
                                      capabilities=sorted(handle.capabilities),
                                      info=probe.info.model_dump(exclude_none=True), seen=True)
        await self._set_status(runtime, "online", "; ".join(probe.warnings) or None, persist=False)
        runtime.ready.set()
        await self._notify(runtime, True)
        try:
            while True:
                await asyncio.sleep(self.HEALTH_INTERVAL_S)
                health = await asyncio.wait_for(handle.health(), timeout=15)
                if not health.online:
                    raise Unavailable(health.detail or "device went offline")
                await self.devices.set_status(device.id, status="online", seen=True)
        finally:
            runtime.ready.clear()
            await self._notify(runtime, False)
            await self._teardown(runtime)
            if runtime.status == "online":
                await self._set_status(runtime, "offline", "connection lost")

    async def _teardown(self, runtime: DeviceRuntime) -> None:
        handle, runtime.handle = runtime.handle, None
        if handle is not None:
            with contextlib.suppress(Exception):
                await handle.close()
        for name in (runtime.stream, runtime.sub_stream):
            if name:
                await self.go2rtc.delete_stream(name)
        runtime.stream = runtime.sub_stream = None

    async def _notify(self, runtime: DeviceRuntime, ready: bool) -> None:
        for listener in self._listeners:
            try:
                await listener(runtime, ready)
            except Exception as exc:
                log.warning("device listener failed", device=runtime.device_id, error=str(exc))

    async def _set_status(self, runtime: DeviceRuntime, status: str, detail: str | None,
                          *, persist: bool = True) -> None:
        changed = runtime.status != status
        runtime.status, runtime.detail = status, detail
        if persist:
            await self.devices.set_status(runtime.device_id, status=status, detail=detail)
        if changed:
            await self.bus.publish(Event(
                type="device.status.changed",
                source=EventSource(kind="device", device_id=runtime.device_id,
                                   room_id=runtime.room_id),
                payload={"device_id": runtime.device_id, "name": runtime.name,
                         "status": status, "detail": detail},
            ))
