"""Process entry point."""

from __future__ import annotations

import uvicorn

from app.api.router import create_app
from app.core.config import load_settings

app = create_app()


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server.host,
        port=settings.server.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
