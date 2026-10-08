import logging

from core.interfaces.http.log import ClockAccessFormatter, ClockDefaultFormatter


def _record(level: int, name: str, msg: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_the_clock_sits_immediately_after_the_level_name() -> None:
    formatter = ClockDefaultFormatter("%(levelprefix)s %(message)s", use_colors=False)
    record = _record(logging.ERROR, "uvicorn.error", "boom")
    clock = formatter.formatTime(record, "%H:%M:%S")

    line = formatter.format(record)

    assert line.startswith(f"ERROR {clock}:")
    assert line.endswith(" boom")
    assert len(clock) == 8


def test_an_access_line_keeps_the_request_after_the_clock() -> None:
    formatter = ClockAccessFormatter(
        '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    )
    record = _record(
        logging.INFO,
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:63904", "GET", "/api/v1/google/accounts", "1.1", 200),
    )
    clock = formatter.formatTime(record, "%H:%M:%S")

    line = formatter.format(record)

    assert line.startswith(f"INFO {clock}:")
    assert '127.0.0.1:63904 - "GET /api/v1/google/accounts HTTP/1.1" 200 OK' in line


def test_color_stays_on_the_level_word() -> None:
    formatter = ClockDefaultFormatter("%(levelprefix)s %(message)s", use_colors=True)
    record = _record(logging.INFO, "uvicorn.error", "ready")
    clock = formatter.formatTime(record, "%H:%M:%S")

    line = formatter.format(record)

    assert f"INFO\033[0m {clock}:" in line
