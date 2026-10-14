"""Outbound HTTP for plugins: host allowlist + SSRF protection."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from justai_sdk.plugin import HttpResponse, PermissionDenied, PluginHttp


def _is_private(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]) for i in infos})


class AllowlistHttp(PluginHttp):
    MAX_BODY = 5 * 1024 * 1024

    def __init__(self, plugin_id: str, allowlist: list[str], *, allow_lan: bool = False) -> None:
        self.plugin_id = plugin_id
        self.allowlist = [h.lower() for h in allowlist]
        self.allow_lan = allow_lan
        self._client = httpx.AsyncClient(follow_redirects=False,
                                         headers={"User-Agent": f"JuStAI5-plugin/{plugin_id}"})

    def _host_allowed(self, host: str) -> bool:
        host = host.lower()
        return any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in self.allowlist)

    async def request(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                      json: Any = None, headers: dict[str, str] | None = None,
                      timeout_s: float = 10.0) -> HttpResponse:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise PermissionDenied("network.http", "only http(s) URLs are allowed")
        if not self._host_allowed(parsed.hostname):
            raise PermissionDenied("network.http", f"host {parsed.hostname} not in allowlist")
        if not self.allow_lan:
            for addr in await _resolve(parsed.hostname):
                if _is_private(addr):
                    raise PermissionDenied("network.lan", f"{parsed.hostname} resolves to {addr}")
        response = await self._client.request(method, url, params=params, json=json,
                                              headers=headers, timeout=timeout_s)
        body = response.content[: self.MAX_BODY]
        return HttpResponse(status=response.status_code,
                            headers={k: v for k, v in response.headers.items()},
                            text=body.decode(response.encoding or "utf-8", errors="replace"))

    async def aclose(self) -> None:
        await self._client.aclose()
