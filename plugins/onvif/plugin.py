"""ONVIF/RTSP cameras and network discovery (WS-Discovery unicast probe, mDNS)."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import re
import uuid
from typing import Any, ClassVar
from urllib.parse import quote, urlparse, urlunparse

from justai_sdk.contrib.onvif_ptz import OnvifPtz
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
from justai_sdk.ports.ptz import PtzController

ONVIF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["host"],
    "properties": {
        "host": {"type": "string", "title": "IP-Adresse / Hostname"},
        "port": {"type": "integer", "default": 80, "title": "ONVIF-Port (Tapo: 2020)"},
        "username": {"type": "string"},
        "password": {"type": "string"},
        "backchannel": {"type": "boolean", "default": False,
                        "description": "Kamera unterstützt ONVIF-Audio-Backchannel (Profil T)"},
        "horizontal_fov_deg": {"type": "number", "default": 90},
    },
    "additionalProperties": False,
}
RTSP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string", "title": "RTSP-URL ohne Zugangsdaten",
                "description": "z. B. rtsp://192.168.0.50:554/stream1"},
        "sub_url": {"type": "string", "title": "Substream-URL (optional)"},
        "username": {"type": "string"},
        "password": {"type": "string"},
        "backchannel": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}


def with_credentials(url: str, user: str | None, password: str | None) -> str:
    if not user:
        return url
    p = urlparse(url)
    netloc = f"{quote(user, safe='')}:{quote(password or '', safe='')}@{p.hostname}"
    if p.port:
        netloc += f":{p.port}"
    return urlunparse(p._replace(netloc=netloc))


async def tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError):
        return False
    w.close()
    return True


class Handle(BaseDeviceHandle):
    def __init__(self, device_id: str, caps: set[str], media: Go2rtcMedia, ptz: PtzController | None,
                 host: str, port: int) -> None:
        super().__init__(device_id, caps)
        self._media, self._ptz, self.host, self.port = media, ptz, host, port

    def media(self) -> Go2rtcMedia:
        return self._media

    def ptz(self) -> PtzController | None:
        return self._ptz

    async def health(self) -> DeviceHealth:
        ok = await tcp_open(self.host, self.port, 3)
        return DeviceHealth(online=ok, detail=None if ok else "not reachable")


class OnvifDriver:
    driver_id = "onvif"
    display_name = "ONVIF-Kamera"

    def config_schema(self) -> dict[str, Any]:
        return ONVIF_SCHEMA

    def secret_fields(self) -> list[str]:
        return ["password"]

    async def probe(self, config: dict[str, Any]) -> ProbeResult:
        from onvif import ONVIFCamera

        host, port = config["host"], int(config.get("port", 80))
        try:
            cam = ONVIFCamera(host, port, config.get("username", ""), config.get("password", ""))
            await asyncio.wait_for(cam.update_xaddrs(), 15)
            dev = await cam.create_devicemgmt_service()
            info = await dev.GetDeviceInformation()
            media = await cam.create_media_service()
            profiles = await media.GetProfiles()
            uris = []
            for prof in profiles[:2]:
                uri = await media.GetStreamUri({"StreamSetup": {"Stream": "RTP-Unicast",
                                                                "Transport": {"Protocol": "RTSP"}},
                                               "ProfileToken": prof.token})
                uris.append(with_credentials(uri.Uri, config.get("username"), config.get("password")))
            has_audio = any(getattr(p, "AudioEncoderConfiguration", None) for p in profiles)
            has_ptz = any(getattr(p, "PTZConfiguration", None) for p in profiles)
            await cam.close()
        except Exception as exc:
            return ProbeResult(ok=False, error=f"ONVIF: {type(exc).__name__}: {exc}")
        caps = {Capability.VIDEO_INPUT, Capability.CAMERA_SNAPSHOT}
        if has_audio:
            caps.add(Capability.AUDIO_INPUT)
        if config.get("backchannel"):
            caps.add(Capability.AUDIO_OUTPUT)
        if has_ptz:
            caps |= {Capability.PTZ_PAN, Capability.PTZ_TILT}
        return ProbeResult(ok=True, capabilities=sorted(caps), info=DeviceInfo(
            manufacturer=info.Manufacturer, model=info.Model, firmware=info.FirmwareVersion,
            serial=info.SerialNumber), media=Go2rtcMedia(
            sources=[uris[0] + ("" if config.get("backchannel") else "#backchannel=0")],
            sub_sources=uris[1:2], backchannel=bool(config.get("backchannel"))))

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> Handle:
        caps = set(probe.capabilities)
        ptz: PtzController | None = None
        if Capability.PTZ_PAN in caps:
            onvif = OnvifPtz(config["host"], int(config.get("port", 80)), config.get("username", ""),
                             config.get("password", ""), hfov_deg=float(config.get("horizontal_fov_deg", 90)))
            with contextlib.suppress(Exception):
                pc = await onvif.connect()
                if pc.pan:
                    ptz = onvif
                    if pc.presets:
                        caps.add(Capability.PTZ_PRESETS)
                    if pc.zoom:
                        caps.add(Capability.PTZ_ZOOM)
                    if pc.absolute:
                        caps.add(Capability.PTZ_ABSOLUTE)
            if ptz is None:
                caps -= {Capability.PTZ_PAN, Capability.PTZ_TILT}
        assert probe.media is not None
        return Handle(device_id, caps, probe.media, ptz, config["host"], int(config.get("port", 80)))


class RtspDriver:
    driver_id = "rtsp"
    display_name = "RTSP-Stream"

    def config_schema(self) -> dict[str, Any]:
        return RTSP_SCHEMA

    def secret_fields(self) -> list[str]:
        return ["password"]

    async def probe(self, config: dict[str, Any]) -> ProbeResult:
        url = config["url"]
        p = urlparse(url)
        if p.scheme not in ("rtsp", "rtsps") or not p.hostname:
            return ProbeResult(ok=False, error="URL must start with rtsp://")
        if p.username or p.password:
            return ProbeResult(ok=False, error="put credentials into username/password, not the URL")
        if not await tcp_open(p.hostname, p.port or 554, 3):
            return ProbeResult(ok=False, error=f"{p.hostname} not reachable")
        main = with_credentials(url, config.get("username"), config.get("password"))
        sub = with_credentials(config["sub_url"], config.get("username"), config.get("password")) \
            if config.get("sub_url") else None
        caps = {Capability.VIDEO_INPUT, Capability.CAMERA_SNAPSHOT, Capability.AUDIO_INPUT}
        if config.get("backchannel"):
            caps.add(Capability.AUDIO_OUTPUT)
        return ProbeResult(ok=True, capabilities=sorted(caps), media=Go2rtcMedia(
            sources=[main + ("" if config.get("backchannel") else "#backchannel=0")],
            sub_sources=[sub] if sub else [], backchannel=bool(config.get("backchannel"))),
            warnings=["Audio-/Videospuren werden am echten Stream überprüft"])

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> Handle:
        p = urlparse(config["url"])
        assert probe.media is not None
        return Handle(device_id, set(probe.capabilities), probe.media, None, p.hostname or "", p.port or 554)


PROBE = ('<?xml version="1.0" encoding="UTF-8"?><e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
         'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
         'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
         'xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><e:Header>'
         '<w:MessageID>uuid:{id}</w:MessageID><w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
         '<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header><e:Body>'
         '<d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>')


class OnvifDiscovery:
    """Unicast WS-Discovery probe (works from a bridged container, unlike multicast)."""

    discovery_id = "onvif"

    async def discover(self, scope: DiscoveryScope) -> list[DiscoveredDevice]:
        hosts = [str(h) for cidr in scope.cidrs for h in ipaddress.ip_network(cidr, strict=False).hosts()]
        loop = asyncio.get_running_loop()
        found: dict[str, DiscoveredDevice] = {}

        class Proto(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                text = data.decode(errors="ignore")
                if "ProbeMatch" not in text:
                    return
                xaddrs = re.findall(r"XAddrs>([^<]+)<", text)
                scopes = " ".join(re.findall(r"Scopes>([^<]+)<", text))
                name = re.search(r"onvif://www.onvif.org/name/([^\s]+)", scopes)
                hw = re.search(r"onvif://www.onvif.org/hardware/([^\s]+)", scopes)
                port = 80
                if xaddrs:
                    with contextlib.suppress(ValueError):
                        port = urlparse(xaddrs[0].split()[0]).port or 80
                found[addr[0]] = DiscoveredDevice(
                    fingerprint=f"onvif:{addr[0]}", host=addr[0], name=name.group(1) if name else None,
                    model=hw.group(1) if hw else None, protocols=["onvif"],
                    suggested_driver="onvif", suggested_config={"host": addr[0], "port": port},
                    requires_credentials=True, discovered_by="onvif")

        transport, _ = await loop.create_datagram_endpoint(Proto, local_addr=("0.0.0.0", 0))
        try:
            for host in hosts:
                transport.sendto(PROBE.format(id=uuid.uuid4()).encode(), (host, 3702))
                await asyncio.sleep(0.002)
            await asyncio.sleep(min(scope.timeout_s, 5.0))
        finally:
            transport.close()
        return list(found.values())


class MdnsDiscovery:
    """mDNS browsing (needs host networking to see multicast; harmless otherwise)."""

    discovery_id = "mdns"
    SERVICES: ClassVar[dict[str, tuple[str, str]]] = {
        "_googlecast._tcp.local.": ("Google Cast / Google TV", "display"),
        "_airplay._tcp.local.": ("AirPlay", "display"),
        "_home-assistant._tcp.local.": ("Home Assistant", "integration"),
        "_rtsp._tcp.local.": ("RTSP-Kamera", "camera"),
    }

    async def discover(self, scope: DiscoveryScope) -> list[DiscoveredDevice]:
        from zeroconf import ServiceStateChange
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

        nets = [ipaddress.ip_network(c, strict=False) for c in scope.cidrs]
        zc = AsyncZeroconf()
        names: list[tuple[str, str]] = []

        def on_change(zeroconf: Any, service_type: str, name: str, state_change: Any) -> None:
            if state_change is ServiceStateChange.Added:
                names.append((service_type, name))

        browser = AsyncServiceBrowser(zc.zeroconf, list(self.SERVICES), handlers=[on_change])
        await asyncio.sleep(min(scope.timeout_s, 4.0))
        out: list[DiscoveredDevice] = []
        for service_type, name in names:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(zc.zeroconf, 1500):
                continue
            for addr in info.parsed_addresses():
                ip = ipaddress.ip_address(addr)
                if not any(ip in n for n in nets):
                    continue
                label, _kind = self.SERVICES[service_type]
                friendly = (info.properties or {}).get(b"fn") or name.split(".")[0].encode()
                out.append(DiscoveredDevice(
                    fingerprint=f"mdns:{name}", host=addr, name=friendly.decode(errors="ignore"),
                    model=label, protocols=[f"mdns:{service_type.split('.')[0]}"],
                    suggested_driver=None, discovered_by="mdns"))
        await browser.async_cancel()
        await zc.async_close()
        return out


class OnvifPlugin(Plugin):
    async def setup(self) -> None:
        self.ctx.register_provider("device_driver", OnvifDriver())
        self.ctx.register_provider("device_driver", RtspDriver())
        self.ctx.register_provider("discovery", OnvifDiscovery())
        self.ctx.register_provider("discovery", MdnsDiscovery())


