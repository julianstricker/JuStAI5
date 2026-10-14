"""Process entry point: ``python -m justai.main``."""

from __future__ import annotations

import uvicorn

from justai.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "justai.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
        proxy_headers=True,
        reload=settings.is_dev,
        reload_dirs=["/app/backend/src", "/app/plugins"] if settings.is_dev else None,
    )


if __name__ == "__main__":
    main()
