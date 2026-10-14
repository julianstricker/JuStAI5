"""Device discovery across all registered discovery providers.

Scans are limited to admin-authorised network ranges (settings ``system.discovery_cidrs``)
and capped in size. Results are annotated with already configured devices.
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

from justai_sdk.ports.discovery import DiscoveredDevice, DiscoveryScope

from justai.common.errors import ValidationFailed
from justai.devices.service import DeviceService
from justai.logging import get_logger
from justai.plugins.providers import ProviderRegistry

log = get_logger(__name__)
MAX_HOSTS = 4096


def validate_cidrs(cidrs: list[str], authorised: list[str]) -> list[str]:
    if not cidrs:
        raise ValidationFailed("no network range given")
    allowed = [ipaddress.ip_network(a, strict=False) for a in authorised]
    total = 0
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValidationFailed(f"invalid range {cidr}") from exc
        if not net.is_private:
            raise ValidationFailed(f"{cidr} is not a private network range")
        if not any(net.subnet_of(a) for a in allowed if a.version == net.version):  # type: ignore[arg-type]
            raise ValidationFailed(f"{cidr} is not inside the authorised ranges {authorised}")
        total += net.num_addresses
    if total > MAX_HOSTS:
        raise ValidationFailed(f"scan too large ({total} addresses, max {MAX_HOSTS})")
    return cidrs


class DiscoveryService:
    def __init__(self, providers: ProviderRegistry, devices: DeviceService) -> None:
        self.providers = providers
        self.devices = devices

    async def scan(self, cidrs: list[str], authorised: list[str], timeout_s: float = 8.0) -> list[dict[str, Any]]:
        validate_cidrs(cidrs, authorised)
        scope = DiscoveryScope(cidrs=cidrs, timeout_s=timeout_s, max_hosts=MAX_HOSTS)
        providers = self.providers.all("discovery")

        async def run(provider: Any) -> list[DiscoveredDevice]:
            try:
                return await asyncio.wait_for(provider.discover(scope), timeout=timeout_s + 30)
            except Exception as exc:
                log.warning("discovery provider failed", provider=getattr(provider, "discovery_id", "?"),
                            error=str(exc))
                return []

        results = [d for batch in await asyncio.gather(*(run(p) for p in providers)) for d in batch]
        # Merge by host: keep the most specific suggestion, union of protocols.
        merged: dict[str, DiscoveredDevice] = {}
        for d in results:
            existing = merged.get(d.host)
            if existing is None:
                merged[d.host] = d
                continue
            protocols = sorted(set(existing.protocols) | set(d.protocols))
            better = d if (d.suggested_driver and d.model) and not existing.model else existing
            merged[d.host] = better.model_copy(update={"protocols": protocols})
        known = {str(dev.config.get("host", "")): dev.id for dev in await self.devices.list()}
        known_fp = {dev.fingerprint: dev.id for dev in await self.devices.list() if dev.fingerprint}
        out = []
        for d in sorted(merged.values(), key=lambda x: ipaddress.ip_address(x.host)):
            item = d.model_dump()
            item["known_device_id"] = known.get(d.host) or known_fp.get(d.fingerprint)
            out.append(item)
        return out
