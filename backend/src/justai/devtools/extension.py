"""Plugin development exposed to the assistant: develop, check the state, revise."""

from __future__ import annotations

from typing import TYPE_CHECKING

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.devtools.service import DevToolsService

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry


class DevelopParams(BaseModel):
    request: str = Field(description="Description of the desired new capability, in the user's words")


class ReviseParams(BaseModel):
    project: str = Field(description="Title, plugin id or project id of the developed plugin")
    change: str = Field(description="What should change, in the user's words")


def _match(projects: list[dict[str, object]], key: str) -> dict[str, object] | None:
    key = key.strip().lower()
    for p in projects:
        if key in (str(p["id"]).lower(), str(p["plugin_id"]).lower()):
            return p
    hits = [p for p in projects if key in str(p["title"]).lower() or key in str(p["request"]).lower()]
    return hits[0] if len(hits) == 1 else None


class DevToolsExtension:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.service = DevToolsService(c)

    def register_tools(self, reg: ToolRegistry) -> None:
        async def develop(p: DevelopParams, ctx: ToolContext) -> ToolResult:
            project_id = await self.service.create(p.request, {"session_id": ctx.session_id,
                                                               "person_id": ctx.person_id})
            return ToolResult.success({"project_id": project_id}, message=(
                "I first check existing capabilities and otherwise develop a new plugin. It is tested "
                "in isolation and only activated after an administrator approves it (admin interface, "
                "Tools). Settings such as API keys are entered there."))

        reg.register(ToolDefinition(
            name="tools.develop",
            description="Develops a new capability as a sandboxed plugin when no existing tool fits "
                        "(check system.capabilities first). A plugin can offer tools, watch something in "
                        "the background (e.g. a price, a level, a website) and publish events that "
                        "automations react to (e.g. 'tell me when electricity is cheaper than 20 cents'), "
                        "and can have its own settings and API keys. Activation only after admin approval.",
            parameters=DevelopParams, category="system", side_effect=SideEffect.WRITE,
            permissions=[Permission.TOOLS_DEVELOP]), develop)

        async def projects(_: NoParams, ctx: ToolContext) -> ToolResult:
            rows = await self.service.list()
            return ToolResult.success([
                {"title": p["title"], "plugin_id": p["plugin_id"], "status": p["status"],
                 "active_version": p["active_version"],
                 "events": (p["versions"][0]["spec"].get("events") if p["versions"] else None) or []}
                for p in rows[:20]],
                message="Status values: analyzing, generating, needs_revision, awaiting_approval (admin must "
                        "approve), needs_config (settings missing), active, inactive, covered_by_existing.")

        reg.register(ToolDefinition(
            name="tools.projects",
            description="Lists the self-developed plugins with their state (e.g. 'is my pollen plugin "
                        "ready?') and the events they publish (usable as automation triggers).",
            parameters=NoParams, category="system", permissions=[Permission.TOOLS_DEVELOP]), projects)

        async def revise(p: ReviseParams, ctx: ToolContext) -> ToolResult:
            project = _match(await self.service.list(), p.project)
            if project is None:
                return ToolResult.failure("not_found", f"no unique project matches '{p.project}'; "
                                                       "use tools.projects to look it up")
            await self.service.revise(str(project["id"]), p.change)
            return ToolResult.success({"project": project["title"]}, message=(
                "A new version is being developed and tested; the administrator approves it in the "
                "admin interface (Tools). The current version keeps running until then."))

        reg.register(ToolDefinition(
            name="tools.revise",
            description="Changes a self-developed plugin (e.g. 'the pollen plugin should also report "
                        "grasses'): develops and tests a new version that an admin approves.",
            parameters=ReviseParams, category="system", side_effect=SideEffect.WRITE,
            permissions=[Permission.TOOLS_DEVELOP]), revise)
