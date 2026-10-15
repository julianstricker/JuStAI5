"""TP-Link Tapo camera driver.

Media: go2rtc ``tapo://`` (video, audio in, two-way audio backchannel) or RTSP.
Control: pytapo (needs the Tapo cloud account password) or ONVIF (needs the
"camera account" configured in the Tapo app; port 2020). Battery models such as
the C410 offer neither RTSP nor ONVIF; only the Tapo protocol is used for them.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import socket
from typing import Any
from urllib.parse import quote

from justai_sdk.plugin import Plugin
from justai_sdk.ports.devices import (
    BaseDeviceHandle,
    Capability,
    DeviceHealth,
    DeviceInfo,
    Go2rtcMedia,
    ProbeResult,
)
from justai_sdk.ports.discovery import DiscoveredDevice, DiscoveryScope
from justai_sdk.ports.ptz import PtzCapabilities, PtzController, PtzPosition, PtzPreset

PORT_TAPO_STREAM = 8800
PORT_RTSP = 554
PORT_ONVIF = 2020
PORT_CONTROL = 443

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["host"],
    "properties": {
        "host": {"type": "string", "title": "IP-Adresse / Hostname"},
        "cloud_password": {"type": "string", "title": "Tapo-Cloud-Passwort",
                           "description": "Für Tapo-Stream mit Zwei-Wege-Audio und lokale Steuerung"},
        "password_hash": {"type": "string", "title": "Passwort-Hash (statt Cloud-Passwort)",
                          "description": "Großgeschriebener MD5/SHA256-Hash des Cloud-Passworts"},
        "camera_username": {"type": "string", "title": "Kamerakonto Benutzer (RTSP/ONVIF)"},
        "camera_password": {"type": "string", "title": "Kamerakonto Passwort"},
        "stream": {"type": "string", "enum": ["tapo", "rtsp"], "default": "tapo"},
        "horizontal_fov_deg": {"type": "number", "default": 95},
        "vertical_fov_deg": {"type": "number", "default": 54},
    },
    "additionalProperties": False,
}
SECRET_FIELDS = ["cloud_password", "password_hash", "camera_password"]


async def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


def tapo_source(host: str, config: dict[str, Any], subtype: int) -> str | None:
    if config.get("password_hash"):
        cred = f"admin:{quote(config['password_hash'], safe='')}"
    elif config.get("cloud_password"):
        cred = quote(config["cloud_password"], safe="")
    else:
        return None
    return f"tapo://{cred}@{host}?subtype={subtype}"


def rtsp_source(host: str, config: dict[str, Any], stream: int) -> str | None:
    if not config.get("camera_username") or not config.get("camera_password"):
        return None
    user = quote(config["camera_username"], safe="")
    pwd = quote(config["camera_password"], safe="")
    return f"rtsp://{user}:{pwd}@{host}:{PORT_RTSP}/stream{stream}"


class PytapoPtz:
    """PTZ through the local Tapo API (pytapo, synchronous -> worker thread)."""

    def __init__(self, tapo: Any, hfov: float, vfov: float, presets: bool) -> None:
        self._tapo = tapo
        self._caps = PtzCapabilities(pan=True, tilt=True, relative=True, presets=presets,
                                     home=presets, horizontal_fov_deg=hfov, vertical_fov_deg=vfov,
                                     pan_range_deg=340, tilt_range_deg=114)
        self._lock = asyncio.Lock()

    @property
    def ptz_capabilities(self) -> PtzCapabilities:
        return self._caps

    async def _call(self, fn: Any, *args: Any) -> Any:
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    async def move_relative(self, pan_fov: float, tilt_fov: float, zoom: float = 0.0) -> None:
        # Tapo motorMove takes relative coordinates in (approximately) degrees.
        x = round(pan_fov * self._caps.horizontal_fov_deg)
        y = round(tilt_fov * self._caps.vertical_fov_deg)
        if x or y:
            await self._call(self._tapo.moveMotor, x, y)

    async def continuous_move(self, pan_speed: float, tilt_speed: float, zoom_speed: float = 0.0,
                              duration_s: float = 0.5) -> None:
        await self.move_relative(pan_speed * duration_s, tilt_speed * duration_s)

    async def stop(self) -> None:
        return None  # relative moves stop by themselves

    async def get_position(self) -> PtzPosition | None:
        return None

    async def move_absolute(self, position: PtzPosition) -> None:
        raise NotImplementedError("Tapo cameras do not support absolute positioning")

    async def list_presets(self) -> list[PtzPreset]:
        presets = await self._call(self._tapo.getPresets)
        return [PtzPreset(id=str(k), name=str(v)) for k, v in (presets or {}).items()]

    async def goto_preset(self, preset_id: str) -> None:
        await self._call(self._tapo.setPreset, preset_id)

    async def save_preset(self, name: str) -> PtzPreset:
        await self._call(self._tapo.savePreset, name)
        for p in await self.list_presets():
            if p.name == name:
                return p
        raise RuntimeError("preset was not saved")

    async def delete_preset(self, preset_id: str) -> None:
        await self._call(self._tapo.deletePreset, preset_id)

    async def go_home(self) -> None:
        # The Tapo API has no home position: a preset named "home" serves as one.
        for p in await self.list_presets():
            if p.name.lower() in ("home", "start", "standard", "default"):
                await self.goto_preset(p.id)
                return
        raise NotImplementedError("no preset named 'home'")


class TapoHandle(BaseDeviceHandle):
    def __init__(self, device_id: str, caps: set[str], media: Go2rtcMedia | None,
                 ptz: PtzController | None, host: str) -> None:
        super().__init__(device_id, caps)
        self._media = media
        self._ptz = ptz
        self.host = host

    def media(self) -> Go2rtcMedia | None:
        return self._media

    def ptz(self) -> PtzController | None:
        return self._ptz

    async def health(self) -> DeviceHealth:
        ok = await port_open(self.host, PORT_TAPO_STREAM) or await port_open(self.host, PORT_RTSP)
        return DeviceHealth(online=ok, detail=None if ok else "camera not reachable")


class TapoDriver:
    driver_id = "tapo"
    display_name = "TP-Link Tapo"

    def config_schema(self) -> dict[str, Any]:
        return CONFIG_SCHEMA

    def secret_fields(self) -> list[str]:
        return SECRET_FIELDS

    async def _pytapo(self, host: str, config: dict[str, Any]) -> Any:
        if not config.get("cloud_password"):
            return None
        from pytapo import Tapo

        return await asyncio.to_thread(Tapo, host, "admin", config["cloud_password"],
                                       config["cloud_password"])

    async def probe(self, config: dict[str, Any]) -> ProbeResult:
        host = str(config["host"]).strip()
        ports = {p: await port_open(host, p) for p in (PORT_TAPO_STREAM, PORT_RTSP, PORT_ONVIF,
                                                        PORT_CONTROL)}
        if not any(ports.values()):
            return ProbeResult(ok=False, error=f"{host} is not reachable")
        warnings: list[str] = []
        info = DeviceInfo(manufacturer="TP-Link")
        caps: set[str] = set()

        use_rtsp = config.get("stream") == "rtsp"
        if use_rtsp and not ports[PORT_RTSP]:
            warnings.append("RTSP-Port geschlossen (Akku-Modelle haben kein RTSP); verwende das Tapo-Protokoll")
            use_rtsp = False
        if use_rtsp:
            main, sub = rtsp_source(host, config, 1), rtsp_source(host, config, 2)
            backchannel = False
            if main is None:
                return ProbeResult(ok=False, error="RTSP needs the camera account")
            warnings.append("RTSP hat kein Zwei-Wege-Audio; für den Lautsprecher das Tapo-Protokoll verwenden")
        else:
            main, sub = tapo_source(host, config, 0), tapo_source(host, config, 1)
            backchannel = True
            if main is None:
                if rtsp_source(host, config, 1) and ports[PORT_RTSP]:
                    main, sub, backchannel = rtsp_source(host, config, 1), rtsp_source(host, config, 2), False
                    warnings.append("kein Cloud-Passwort: RTSP ohne Lautsprecher")
                else:
                    return ProbeResult(ok=False, error="cloud password (or hash) required")
            elif not ports[PORT_TAPO_STREAM]:
                return ProbeResult(ok=False, error="Tapo stream port 8800 closed")
        # Media capabilities are verified by the core against the real go2rtc stream.
        caps |= {Capability.VIDEO_INPUT, Capability.CAMERA_SNAPSHOT, Capability.AUDIO_INPUT}
        if backchannel:
            caps.add(Capability.AUDIO_OUTPUT)

        tapo = None
        if config.get("cloud_password") and ports[PORT_CONTROL]:
            try:
                tapo = await self._pytapo(host, config)
                basic = await asyncio.to_thread(tapo.getBasicInfo)
                dev = basic.get("device_info", {}).get("basic_info", {})
                info = DeviceInfo(manufacturer="TP-Link", model=dev.get("device_model"),
                                  hardware_version=dev.get("hw_version"),
                                  firmware=dev.get("sw_version"), mac=dev.get("mac"),
                                  extra={"type": dev.get("device_type")})
                with contextlib.suppress(Exception):
                    # Not implemented by every firmware (C200: METHOD_DO_NOT_EXIST).
                    if await asyncio.to_thread(tapo.getMotorCapability):
                        caps |= {Capability.PTZ_PAN, Capability.PTZ_TILT}
                with contextlib.suppress(Exception):
                    # The preset API only exists on pan/tilt models, so it also proves the motor.
                    await asyncio.to_thread(tapo.getPresets)
                    caps |= {Capability.PTZ_PAN, Capability.PTZ_TILT, Capability.PTZ_PRESETS}
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(tapo.getPrivacyMode)
                    caps.add(Capability.CAMERA_PRIVACY_MODE)
            except Exception as exc:
                warnings.append(f"lokale Tapo-API nicht nutzbar: {type(exc).__name__}: {exc}")
        if Capability.PTZ_PAN not in caps and ports[PORT_ONVIF] and config.get("camera_username"):
            caps |= {Capability.PTZ_PAN, Capability.PTZ_TILT}  # confirmed via ONVIF on open()
        if Capability.PTZ_PAN not in caps and not config.get("cloud_password") \
                and not config.get("camera_username"):
            warnings.append("PTZ/Presets brauchen das Cloud-Passwort (lokale API) oder das Kamerakonto (ONVIF)")

        media = Go2rtcMedia(sources=[main], sub_sources=[sub] if sub else [],
                            backchannel=backchannel, backchannel_codec="pcma")
        return ProbeResult(ok=True, capabilities=sorted(caps), info=info, media=media,
                           warnings=warnings)

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> TapoHandle:
        host = str(config["host"]).strip()
        caps = set(probe.capabilities)
        hfov = float(config.get("horizontal_fov_deg", 95))
        vfov = float(config.get("vertical_fov_deg", 54))
        ptz: PtzController | None = None
        if Capability.PTZ_PAN in caps:
            if config.get("cloud_password"):
                try:
                    tapo = await self._pytapo(host, config)
                    ptz = PytapoPtz(tapo, hfov, vfov, Capability.PTZ_PRESETS in caps)
                except Exception:
                    ptz = None
            if ptz is None and config.get("camera_username"):
                from justai_sdk.contrib.onvif_ptz import OnvifPtz

                onvif = OnvifPtz(host, PORT_ONVIF, config["camera_username"],
                                 config.get("camera_password", ""), hfov_deg=hfov, vfov_deg=vfov)
                try:
                    pc = await onvif.connect()
                    if pc.pan:
                        ptz = onvif
                        if pc.presets:
                            caps.add(Capability.PTZ_PRESETS)
                except Exception:
                    ptz = None
            if ptz is None:
                caps -= {Capability.PTZ_PAN, Capability.PTZ_TILT, Capability.PTZ_PRESETS}
        return TapoHandle(device_id, caps, probe.media, ptz, host)


class TapoDiscovery:
    """Finds Tapo cameras by their stream/control ports in authorised ranges."""

    discovery_id = "tapo"

    async def discover(self, scope: DiscoveryScope) -> list[DiscoveredDevice]:
        hosts: list[str] = []
        for cidr in scope.cidrs:
            net = ipaddress.ip_network(cidr, strict=False)
            hosts += [str(h) for h in net.hosts()][: scope.max_hosts - len(hosts)]
        sem = asyncio.Semaphore(128)

        async def check(host: str) -> DiscoveredDevice | None:
            async with sem:
                if not await port_open(host, PORT_TAPO_STREAM, timeout=0.8):
                    return None
                rtsp = await port_open(host, PORT_RTSP, timeout=0.8)
                onvif = await port_open(host, PORT_ONVIF, timeout=0.8)
            name = None
            with contextlib.suppress(Exception):
                name = (await asyncio.to_thread(socket.gethostbyaddr, host))[0]
            protocols = ["tapo"] + (["rtsp"] if rtsp else []) + (["onvif"] if onvif else [])
            fingerprint = "tapo:" + hashlib.sha1(host.encode()).hexdigest()[:12]
            return DiscoveredDevice(
                fingerprint=fingerprint, host=host, name=name, manufacturer="TP-Link",
                model="Tapo (battery model)" if not rtsp else "Tapo camera", protocols=protocols,
                suggested_driver="tapo", suggested_config={"host": host},
                requires_credentials=True, discovered_by="tapo")

        results = await asyncio.gather(*(check(h) for h in hosts))
        return [r for r in results if r is not None]


class TapoPlugin(Plugin):
    async def setup(self) -> None:
        self.ctx.register_provider("device_driver", TapoDriver())
        self.ctx.register_provider("discovery", TapoDiscovery())
