"""Shared document contract. Mirrored by web/src/lib/types.ts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal["paper", "note", "email", "event", "file", "task"]


class Document(BaseModel):
    id: str  # f"{source}:{source_id}"
    source: SourceKind
    source_id: str  # id in the originating system
    title: str
    uri: str  # clickable link back to the original
    author: str | None = None
    participants: list[str] = Field(default_factory=list)
    collection: str | None = None
    created_at: datetime
    updated_at: datetime
    content_hash: str  # incremental-index key
    extra: dict[str, Any] = Field(default_factory=dict)


class BBox(BaseModel):
    """Where a chunk sits on the page, for highlighting the original.

    Coordinates are fractions of the page box with a top-left origin, so
    the reader can place them at any zoom without knowing the PDF's
    point size.
    """

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class Chunk(BaseModel):
    """Retrieved text plus everything needed to point back at the source.

    `text` is canonical. A vector is only an index into this row, never a
    replacement for it, so re-embedding never risks the quoted words.
    """

    id: str
    doc_id: str
    ord: int
    text: str
    token_count: int = 0
    page_start: int = 1
    page_end: int = 1
    section_path: str | None = None
    section_kind: str | None = None
    bboxes: list[BBox] = Field(default_factory=list)
    char_start: int = 0
    char_end: int = 0

    @property
    def locator(self) -> dict[str, Any]:
        """The shape citations travel in over SSE."""
        found: dict[str, Any] = {"page": self.page_start}
        if self.page_end != self.page_start:
            found["page_end"] = self.page_end
        if self.section_path:
            found["section"] = self.section_path
        if self.bboxes:
            found["bboxes"] = [box.model_dump() for box in self.bboxes]
        return found


class Citation(BaseModel):
    n: int
    kind: SourceKind
    doc_id: str
    title: str
    uri: str
    locator: dict[str, Any] = Field(default_factory=dict)
    snippet: str


class StructuredQuery(BaseModel):
    text: str
    sources: list[SourceKind] | None = None
    time_range: tuple[datetime, datetime] | None = None
    people: list[str] = Field(default_factory=list)
    collection: str | None = None
