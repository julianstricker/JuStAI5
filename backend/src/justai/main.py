"""Process entry point: ``python -m justai.main``.

Serves HTTP (admin UI, API) and - unless disabled - HTTPS with a certificate of the
local JuStAI5 CA (device app: browsers allow microphone/camera only on secure origins).
Both servers share one application; only the HTTP server runs the lifespan.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn

import justai
from justai.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.is_dev:
        uvicorn.run(
            "justai.api.app:create_app", factory=True, host=settings.host, port=settings.port,
            log_config=None, proxy_headers=True, reload=True,
            reload_dirs=[str(Path(justai.__file__).parent), str(settings.builtin_plugins_dir)])
        return
    asyncio.run(_serve())


async def _serve() -> None:
    from justai.api.app import create_app

    settings = get_settings()
    app = create_app(settings)
    servers = [uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_config=None,
                                             proxy_headers=True))]
    tls = getattr(app.state, "tls", None)
    if tls is not None:
        config = uvicorn.Config(app, host=settings.host, port=settings.https_port, log_config=None,
                                proxy_headers=True, lifespan="off")
        config.load()
        config.ssl = tls.server_context()  # reloadable when names are added
        servers.append(uvicorn.Server(config))
    await asyncio.gather(*(server.serve() for server in servers))


if __name__ == "__main__":
    main()
