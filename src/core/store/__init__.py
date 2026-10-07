"""SQLite-backed state. The metadata database lives under `data_dir`."""

from core.store.documents import DocumentStore, IndexedDocument, ScoredChunk
from core.store.sources import SourceRecord, SourceStore
from core.store.vectors import SqliteVecStore, VectorHit, VectorStore

__all__ = [
    "DocumentStore",
    "IndexedDocument",
    "ScoredChunk",
    "SourceRecord",
    "SourceStore",
    "SqliteVecStore",
    "VectorHit",
    "VectorStore",
]
