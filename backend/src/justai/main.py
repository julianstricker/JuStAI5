"""Process entry point: ``python -m justai.main``."""

from __future__ import annotations

from pathlib import Path

import uvicorn

import justai
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
        reload_dirs=[str(Path(justai.__file__).parent), str(settings.builtin_plugins_dir)]
        if settings.is_dev else None,
    )


if __name__ == "__main__":
    main()
