"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from justai import __version__
from justai.common.errors import JustAIError
from justai.config import Settings, get_settings
from justai.container import Container
from justai.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(settings: Settings | None = None, *, start_container: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = Container(settings)
        app.state.container = container
        if start_container:
            await container.start()
        try:
            yield
        finally:
            await container.stop()

    app = FastAPI(title="JuStAI5", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(JustAIError)
    async def domain_error(_: Request, exc: JustAIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"error": exc.code, "message": exc.message,
                                     "details": exc.details or None})

    from justai.api.routes import (
        ai,
        auth,
        conversations,
        devices,
        endpoints,
        extensions,
        plugins,
        rooms,
        system,
    )

    for module in (auth, rooms, devices, endpoints, plugins, ai, conversations, system):
        app.include_router(module.router)
    for router in extensions.routers():
        app.include_router(router)

    _mount_frontend(app, settings.static_dir)
    return app


def _mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built admin UI (/) and display client (/display) if present."""
    if not static_dir.exists():
        return
    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/display", include_in_schema=False)
    @app.get("/display/{_path:path}", include_in_schema=False)
    async def display_client(_path: str = "") -> FileResponse:
        return FileResponse(static_dir / "display.html")

    @app.get("/{_path:path}", include_in_schema=False)
    async def spa(_path: str) -> FileResponse:
        candidate = static_dir / _path
        if _path and candidate.is_file() and static_dir in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
