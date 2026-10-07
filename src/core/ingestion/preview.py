"""Turn a fetched file into located chunks or a text preview."""

from __future__ import annotations

from core.connectors.base import RawDocument
from core.domain.errors import ParseError
from core.domain.models import Chunk
from core.ingestion.chunk.structure import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MIN_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    blocks_from_pages,
    chunk_document,
)
from core.ingestion.parse import get_parser
from core.ingestion.parse.base import LayoutBlock, PageText, ParsedDocument


def parse_document(raw: RawDocument) -> ParsedDocument:
    """Parse `raw` with the parser registered for `extra['format']`."""
    fmt = str(raw.extra.get("format", ""))
    if fmt in {"markdown", "plain"}:
        text = raw.content.decode("utf-8", errors="replace")
        return ParsedDocument(pages=[PageText(page=1, text=text)])
    parser = get_parser(fmt)
    if parser is None:
        raise ParseError(f"No parser for format {fmt!r}")
    return parser.parse(raw.content)


def parse_to_chunks(
    raw: RawDocument,
    *,
    chunking_version: str = "v2-preview",
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    parsed = parse_document(raw)
    return chunk_document(
        f"{raw.source}:{raw.source_id}",
        blocks_for(parsed),
        chunking_version=chunking_version,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        overlap_tokens=overlap_tokens,
    )


def blocks_for(parsed: ParsedDocument) -> list[LayoutBlock]:
    """Layout when the parser saw the page, text-derived blocks otherwise."""
    if parsed.blocks:
        return list(parsed.blocks)
    return blocks_from_pages(parsed.pages)


def preview_document(raw: RawDocument) -> ParsedDocument:
    """Pages and, for Word, the blocks the reader draws.

    Unknown formats stay empty rather than raising.
    """
    try:
        return parse_document(raw)
    except ParseError:
        if str(raw.extra.get("format", "")) in {"pdf", "markdown", "plain", "docx"}:
            raise
        return ParsedDocument()


def preview_pages(raw: RawDocument) -> list[PageText]:
    """Text for the viewer. Unknown formats stay empty rather than raising."""
    return preview_document(raw).pages
