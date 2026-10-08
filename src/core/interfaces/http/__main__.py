"""Run the API. `python -m core.interfaces.http`"""

from __future__ import annotations

import uvicorn

from core.config import load_settings
from core.interfaces.http.log import log_config


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "core.interfaces.http.app:app",
        host=settings.host,
        port=settings.port,
        log_config=log_config(),
    )


if __name__ == "__main__":
    main()
