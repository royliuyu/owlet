"""Server log lines, with the clock immediately after the level name.

Uvicorn prints ``INFO:`` and then the request. The clock is the time of
day only, so a line reads ``INFO 19:47:03:`` and the rest stays as it was.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter, DefaultFormatter

_CLOCK = "%H:%M:%S"
# The level word may be wrapped in ANSI color codes. The colon stays put
# until the clock is inserted between the word and that colon.
_LEVEL = re.compile(
    r"^((?:\033\[[0-9;]*m)*)"
    r"(TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"((?:\033\[[0-9;]*m)*):"
)


def _insert_clock(formatter: logging.Formatter, record: logging.LogRecord, line: str) -> str:
    clock = formatter.formatTime(record, _CLOCK)
    return _LEVEL.sub(rf"\1\2\3 {clock}:", line, count=1)


class ClockDefaultFormatter(DefaultFormatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        return _insert_clock(self, record, super().formatMessage(record))


class ClockAccessFormatter(AccessFormatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        return _insert_clock(self, record, super().formatMessage(record))


def log_config() -> dict[str, Any]:
    """Uvicorn's logging setup, with the clock formatters installed."""
    config = deepcopy(LOGGING_CONFIG)
    config["formatters"]["default"]["()"] = "core.interfaces.http.log.ClockDefaultFormatter"
    config["formatters"]["access"]["()"] = "core.interfaces.http.log.ClockAccessFormatter"
    return config
