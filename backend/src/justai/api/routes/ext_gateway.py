"""Plugin gateway: the only way sandboxed plugins reach core functionality.

Each request carries a plugin-scoped token; the requested operation is checked
against the permissions granted to that plugin.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Request
from justai_sdk.events import Event
from justai_sdk.permissions import Permission

from justai.api.deps import C
from justai.common.errors import Forbidden, NotFound, Unauthorized
from justai.plugins.context import DbPluginStore
from justai.plugins.http import AllowlistHttp

router = APIRouter(include_in_schema=False)

OP_PERMISSION = {
    "http": Permission.NETWORK_HTTP,
    "store.get": Permission.STORAGE_PLUGIN, "store.put": Permission.STORAGE_PLUGIN,
    "store.delete": Permission.STORAGE_PLUGIN, "store.keys": Permission.STORAGE_PLUGIN,
    "services.list_devices": Permission.DEVICES_READ, "services.list_rooms": Permission.DEVICES_READ,
    "services.snapshot": Permission.CAMERA_READ, "services.memory_search": Permission.MEMORY_READ,
    "services.say": Permission.SPEAKER_WRITE, "services.show": Permission.DISPLAY_WRITE,
    "services.complete": Permission.AI_INVOKE, "events.publish": Permission.EVENTS_PUBLISH,
}


@router.post("/internal/plugin-gateway/{plugin_id}")
async def gateway(plugin_id: str, request: Request, c: C) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized()
    if c.auth.verify_scoped_token(header[7:], "plugin-gateway") != plugin_id:
        raise Unauthorized("token not valid for this plugin")
    sandbox = c.plugins.sandbox
    if sandbox is None or plugin_id not in sandbox.granted:
        raise NotFound("plugin not running in the sandbox")
    body = await request.json()
    op, args = str(body.get("op")), dict(body.get("args") or {})
    needed = OP_PERMISSION.get(op)
    if needed is None:
        raise Forbidden(f"unknown operation {op}")
    if needed not in sandbox.granted[plugin_id]:
        raise Forbidden(f"permission {needed} not granted to {plugin_id}")
    manifest = sandbox.manifests[plugin_id]
    backend = c.plugins.backend
    if op == "http":
        http = AllowlistHttp(plugin_id, manifest.network_allowlist, allow_lan=False)
        try:
            resp = await http.request(args["method"], args["url"], params=args.get("params"),
                                      json=args.get("json"), headers=args.get("headers"),
                                      timeout_s=float(args.get("timeout_s", 10)))
        finally:
            await http.aclose()
        return {"result": resp.model_dump()}
    if op.startswith("store."):
        store = DbPluginStore(c.db, plugin_id)
        fn = getattr(store, op.split(".", 1)[1])
        return {"result": await fn(**args)}
    if op == "events.publish":
        event = Event.model_validate(args["event"])
        if not event.type.startswith(f"plugin.{plugin_id}."):
            raise Forbidden("sandboxed plugins may only publish plugin.<id>.* events")
        source = event.source.model_copy(update={"kind": "plugin", "plugin_id": plugin_id})
        await c.bus.publish(event.model_copy(update={"source": source}))
        return {"result": True}
    name = op.split(".", 1)[1]
    if name == "say":
        await backend.say(args["room_id"], args["text"], plugin_id)
        return {"result": None}
    if name == "show":
        return {"result": await backend.show(args["room_id"], args["document"], plugin_id)}
    if name == "snapshot":
        return {"result": base64.b64encode(await backend.snapshot(args["device_id"])).decode()}
    if name == "memory_search":
        return {"result": await backend.memory_search(args["query"], args.get("person_id"), int(args.get("limit", 5)))}
    if name == "complete":
        return {"result": await backend.complete(args["prompt"], args.get("role", "background"))}
    return {"result": await getattr(backend, name)()}
