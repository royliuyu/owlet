"""Format → parser lookup. New formats register here and nowhere else."""

from __future__ import annotations

from core.ingestion.parse.base import Parser

_PARSERS: dict[str, Parser] = {}


def register_parser(parser: Parser) -> None:
    _PARSERS[parser.format] = parser


def get_parser(fmt: str) -> Parser | None:
    return _PARSERS.get(fmt)


def registered_formats() -> tuple[str, ...]:
    return tuple(sorted(_PARSERS))
