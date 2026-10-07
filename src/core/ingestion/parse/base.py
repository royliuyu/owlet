"""Parsed pages shared by every format parser."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from core.domain.models import BBox


class PageText(BaseModel):
    """One page of extracted text. `page` is 1-based."""

    page: int
    text: str


class PreviewBlock(BaseModel):
    """Reading order for the viewer. Chunking keeps using `LayoutBlock`."""

    kind: Literal["heading", "paragraph", "list", "table"]
    text: str = ""
    level: int = 1
    ordered: bool = False
    items: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class LayoutBlock(BaseModel):
    """A heading or paragraph with the geometry needed to highlight it.

    Parsers that cannot see the page (Markdown, Word) leave `bboxes`
    empty; chunking degrades to page-level provenance rather than failing.
    """

    kind: Literal["heading", "paragraph"]
    text: str
    page: int
    page_end: int
    bboxes: list[BBox] = Field(default_factory=list)
    font_size: float = 0.0


class ParsedDocument(BaseModel):
    pages: list[PageText] = Field(default_factory=list)
    blocks: list[LayoutBlock] = Field(default_factory=list)
    preview: list[PreviewBlock] = Field(default_factory=list)


class Parser(Protocol):
    """Turn raw bytes into pages. Chunking stays format-agnostic."""

    format: str

    def parse(self, content: bytes) -> ParsedDocument:
        """Extract text. Raise ParseError when the bytes are not this format."""
        ...
