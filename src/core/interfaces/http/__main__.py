"""Run the API. `python -m core.interfaces.http`"""

from __future__ import annotations

import uvicorn

from core.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "core.interfaces.http.app:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
