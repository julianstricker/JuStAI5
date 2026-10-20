"""Display tools for the assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.common.errors import RoutingDenied, ValidationFailed
from justai.display.service import DisplayService

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry

DOC_HELP = (
    "Document: {\"title\":\"...\",\"layout\":\"single|dashboard\",\"components\":[...],"
    "\"duration_s\":120}. Components (type + fields): text{text,size}, heading{text}, "
    "markdown{markdown}, image{src(https)}, table{columns,rows}, kv{items:[{label,value}]}, "
    "stat{label,value,unit,trend}, chart{kind:line|bar|area,x_type:time|category,series:[{name,"
    "points:[[x,y]]}]}, list{items}, weather{location,temperature,condition,forecast:[{day,min,max,"
    "condition}]}, stock-quote{symbol,name,price,currency,change,change_pct}, camera{device_id}, "
    "notification{title,message,level}, choice{prompt,options:[{id,label}]}, button{label,action_id}, "
    "clock{}, card/row/grid{children:[...]}. No HTML. Texts in the user's language.")


class ShowParams(BaseModel):
    document: dict[str, Any] = Field(description=DOC_HELP)
    room: str | None = Field(None, description="Only for an explicit display in ANOTHER room")
    personal: bool = Field(False, description="True for private content (calendar, health, finances)")


class UpdateParams(BaseModel):
    presentation_id: str
    document: dict[str, Any]


class CloseParams(BaseModel):
    presentation_id: str


class DisplayExtension:
    def __init__(self, c: Container, service: DisplayService) -> None:
        self.c = c
        self.service = service

    async def start(self) -> None:
        await self.service.start()

    async def stop(self) -> None:
        await self.service.stop()

    async def present(self, document: dict[str, Any], **kw: Any) -> Any:
        return await self.service.present(document, **kw)

    def register_tools(self, reg: ToolRegistry) -> None:
        svc = self.service

        async def show(p: ShowParams, ctx: ToolContext) -> ToolResult:
            target_room = None
            if p.room:
                room = await self.c.rooms.find(p.room)
                if room is None:
                    return ToolResult.failure("unknown_room", f"unknown room '{p.room}'")
                target_room = room.id
            try:
                pres = await svc.present(
                    p.document, origin_endpoint_id=ctx.endpoint_id, origin_room_id=ctx.room_id,
                    target_room_id=target_room, explicit_cross_room=target_room is not None,
                    permissions=ctx.permissions, personal=p.personal, session_id=ctx.session_id,
                    system=ctx.origin.value == "admin")
            except RoutingDenied as exc:
                return ToolResult.failure(exc.code, exc.message)
            except ValidationFailed as exc:
                return ToolResult.failure("invalid_document", exc.message, data=exc.details)
            if pres.status != "displayed":
                return ToolResult.failure("not_displayed", f"Not displayed: {pres.error or 'no acknowledgement'}",
                                          data={"presentation_id": pres.id, "status": pres.status})
            return ToolResult.success({"presentation_id": pres.id, "status": pres.status},
                                      message="Shown on the display (acknowledged)")

        reg.register(ToolDefinition(
            name="display.show",
            description="Shows structured content on the screen in the room of the conversation and only "
                        "reports success once the display has acknowledged it. " + DOC_HELP,
            parameters=ShowParams, category="display", side_effect=SideEffect.PHYSICAL, timeout_s=20,
            permissions=[Permission.DISPLAY_WRITE]), show)

        async def update(p: UpdateParams, ctx: ToolContext) -> ToolResult:
            pres = await svc.update(p.presentation_id, p.document)
            return ToolResult(ok=pres.status == "updated", data={"status": pres.status},
                              message="Presentation updated" if pres.status == "updated" else "failed")

        reg.register(ToolDefinition(
            name="display.update", description="Updates a displayed presentation.",
            parameters=UpdateParams, category="display", side_effect=SideEffect.PHYSICAL,
            permissions=[Permission.DISPLAY_WRITE]), update)

        async def close(p: CloseParams, ctx: ToolContext) -> ToolResult:
            presentations = {x.id: x for x in await svc.presentations(200)}
            pres = presentations.get(p.presentation_id)
            if pres is None:
                return ToolResult.failure("unknown", "Presentation not found")
            await svc.close(pres.display_device_id, pres.id)
            return ToolResult.success(message="Presentation closed")

        reg.register(ToolDefinition(
            name="display.close", description="Closes a presentation.", parameters=CloseParams,
            category="display", side_effect=SideEffect.PHYSICAL, permissions=[Permission.DISPLAY_WRITE]), close)

        async def list_(_: NoParams, ctx: ToolContext) -> ToolResult:
            items = await svc.list()
            here = [d for d in items if d["room_id"] == ctx.room_id] if ctx.room_id else items
            return ToolResult.success([{"name": d["name"], "connected": d["connected"],
                                        "capabilities": d["capabilities"]} for d in here])

        reg.register(ToolDefinition(
            name="display.list", description="Displays in the current room and their status.",
            parameters=NoParams, category="display", permissions=[Permission.DEVICES_READ]), list_)
