"""Connector protocol shared by every data source."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from core.domain.models import Document, SourceKind


class Change(BaseModel):
    """One upsert or delete discovered since the previous cursor."""

    op: Literal["upsert", "delete"]
    source_id: str
    content_hash: str | None = None
    updated_at: datetime | None = None


class ChangeSet(BaseModel):
    """A page of changes plus the cursor to persist in sync_state."""

    changes: list[Change]
    cursor: str


class RawDocument(BaseModel):
    """Bytes fetched from a source, before parsing or chunking."""

    source_id: str
    source: SourceKind
    title: str
    uri: str
    media_type: str
    content: bytes
    content_hash: str
    created_at: datetime
    updated_at: datetime
    collection: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Connector(Protocol):
    """Unified source adapter.

    list_changes reports what moved, fetch loads one item, resolve_uri
    builds a link back to the original. Parsing stays in ingestion.
    """

    source: SourceKind

    def list_changes(self, cursor: str | None) -> AsyncIterator[ChangeSet]:
        """Yield change pages. Pass None to scan from scratch."""
        ...

    async def fetch(self, source_id: str) -> RawDocument:
        """Load the current bytes for one source id."""
        ...

    def resolve_uri(self, doc: Document) -> str:
        """Return a URI that opens the original item."""
        ...
