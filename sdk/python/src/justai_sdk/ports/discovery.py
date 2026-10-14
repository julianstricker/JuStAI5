"""Discovery port. Scans are always limited to admin-authorised network ranges."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class DiscoveryScope(BaseModel):
    cidrs: list[str]  # authorised ranges, e.g. ["192.168.0.0/24"]
    timeout_s: float = 5.0
    max_hosts: int = 1024


class DiscoveredDevice(BaseModel):
    fingerprint: str  # stable identity (mac, serial or host:protocol)
    host: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    mac: str | None = None
    protocols: list[str] = Field(default_factory=list)  # onvif, rtsp, tapo, mdns:_googlecast ...
    suggested_driver: str | None = None
    suggested_config: dict[str, Any] = Field(default_factory=dict)
    requires_credentials: bool = False
    discovered_by: str = ""


@runtime_checkable
class DiscoveryProvider(Protocol):
    discovery_id: str

    async def discover(self, scope: DiscoveryScope) -> list[DiscoveredDevice]: ...
