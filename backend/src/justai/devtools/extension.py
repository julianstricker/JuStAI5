"""Tool development exposed to the assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from justai_sdk.permissions import Permission
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.devtools.service import DevToolsService

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry


class DevelopParams(BaseModel):
    request: str = Field(description="Description of the desired new capability")


class DevToolsExtension:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.service = DevToolsService(c)

    def register_tools(self, reg: ToolRegistry) -> None:
        async def develop(p: DevelopParams, ctx: ToolContext) -> ToolResult:
            project_id = await self.service.create(p.request, {"session_id": ctx.session_id,
                                                               "person_id": ctx.person_id})
            return ToolResult.success({"project_id": project_id}, message=(
                "I first check existing capabilities and otherwise develop a new tool. It is tested in "
                "isolation and only activated after an administrator approves it (admin interface, "
                "Tools)."))

        reg.register(ToolDefinition(
            name="tools.develop",
            description="Starts developing a new capability when no existing tool fits (check "
                        "system.capabilities first). Activation only after admin approval.",
            parameters=DevelopParams, category="system", side_effect=SideEffect.WRITE,
            permissions=[Permission.TOOLS_DEVELOP]), develop)
