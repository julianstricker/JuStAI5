"""Routers contributed by feature extensions (memory, vision, displays, ...)."""

from __future__ import annotations

from fastapi import APIRouter


def routers() -> list[APIRouter]:
    out: list[APIRouter] = []
    for module_name in ("memory", "vision", "identity", "automation", "display", "discovery",
                        "ptz", "devtools"):
        try:
            module = __import__(f"justai.api.routes.ext_{module_name}", fromlist=["router"])
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith(f"ext_{module_name}"):
                continue
            raise
        out.append(module.router)
    return out
