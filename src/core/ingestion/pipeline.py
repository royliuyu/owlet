"""Build the index: connector → parse → chunk → store → embed.

Incremental on two keys. A document is re-parsed when its content hash
moves, and re-chunked when the chunking version moves; either way the
old chunks and their vectors go first, so a run never leaves a document
half-described by two layouts. Embedding is a separate pass over
whatever has no vector from the current model, which makes a run
interrupted midway safe to repeat.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.config import ChunkSettings
from core.connectors.local_files import LocalFilesConnector
from core.domain.errors import ParseError
from core.ingestion.chunk.structure import chunk_document
from core.ingestion.parse import PARSER_VERSION
from core.ingestion.parse.bibliography import BIBLIOGRAPHY_VERSION, read_bibliography
from core.ingestion.preview import blocks_for, parse_document
from core.llm import EmbeddingClient
from core.store import DocumentStore, VectorStore


@dataclass
class IndexProgress:
    run_id: str
    status: str = "running"
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    chunks_written: int = 0
    chunks_embedded: int = 0
    failures: list[str] = field(default_factory=list)
    detail: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    finished_at: datetime | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "documents_seen": self.documents_seen,
            "documents_indexed": self.documents_indexed,
            "documents_skipped": self.documents_skipped,
            "chunks_written": self.chunks_written,
            "chunks_embedded": self.chunks_embedded,
            "failures": list(self.failures),
            "detail": self.detail,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


ProgressHook = Callable[[IndexProgress], None]


def layout_version(chunking: ChunkSettings) -> str:
    """What a stored chunk's shape depends on: the parser and the settings."""
    return f"{PARSER_VERSION}|{chunking.version}"


class Indexer:
    def __init__(
        self,
        *,
        documents: DocumentStore,
        vectors: VectorStore,
        embedder: EmbeddingClient,
        chunking: ChunkSettings,
    ) -> None:
        self._documents = documents
        self._vectors = vectors
        self._embedder = embedder
        self._chunking = chunking

    async def run(
        self,
        connector: LocalFilesConnector,
        *,
        on_progress: ProgressHook | None = None,
        force: bool = False,
    ) -> IndexProgress:
        progress = IndexProgress(run_id=uuid.uuid4().hex)
        version = layout_version(self._chunking)

        def tick() -> None:
            if on_progress:
                on_progress(progress)

        try:
            current = await connector.list_documents()
            progress.documents_seen = len(current)
            tick()

            known = self._documents.indexed()
            seen_ids = {document.id for document in current}

            stale = [doc_id for doc_id in known if doc_id not in seen_ids]
            if stale:
                self._vectors.delete(self._documents.delete_documents(stale))
                progress.detail = f"Removed {len(stale)} document(s) no longer on disk"
                tick()

            for document in current:
                prior = known.get(document.id)
                unchanged = (
                    prior is not None
                    and prior.content_hash == document.content_hash
                    and prior.chunking_version == version
                )
                if unchanged and not force:
                    if await self._fill_bibliography(connector, document):
                        progress.detail = "Recorded paper details"
                    progress.documents_skipped += 1
                    tick()
                    continue
                try:
                    written = await self._index_one(connector, document, version)
                except ParseError as exc:
                    progress.failures.append(f"{document.title}: {exc}")
                    tick()
                    continue
                progress.documents_indexed += 1
                progress.chunks_written += written
                tick()

            progress.chunks_embedded = await self._embed_pending(progress, tick)
            progress.status = "ok" if not progress.failures else "partial"
        except Exception as exc:  # surfaced to the UI rather than lost in a task
            progress.status = "error"
            progress.detail = str(exc)
        progress.finished_at = datetime.now(tz=timezone.utc)
        tick()
        return progress

    async def _index_one(
        self,
        connector: LocalFilesConnector,
        document,
        version: str,
    ) -> int:
        raw = await connector.fetch(document.source_id)
        record = await self._bibliography(document, raw.content)
        if record is not None:
            extra = {**document.extra, "bibliography": record}
            document = document.model_copy(update={"extra": extra})
        parsed = await asyncio.to_thread(parse_document, raw)
        chunks = await asyncio.to_thread(
            chunk_document,
            document.id,
            blocks_for(parsed),
            chunking_version=version,
            target_tokens=self._chunking.target_tokens,
            max_tokens=self._chunking.max_tokens,
            min_tokens=self._chunking.min_tokens,
            overlap_tokens=self._chunking.overlap_tokens,
        )
        previous = self._documents.chunk_ids_for(document.id)
        self._documents.upsert_document(
            document,
            root_id=str(document.extra.get("root_id", "")),
            page_count=len(parsed.pages),
            parser=str(document.extra.get("format", "")),
        )
        self._documents.replace_chunks(document.id, chunks, chunking_version=version)
        gone = [chunk_id for chunk_id in previous if chunk_id not in {c.id for c in chunks}]
        self._vectors.delete(gone)
        return len(chunks)

    async def _fill_bibliography(self, connector: LocalFilesConnector, document) -> bool:
        """Store the paper record when this file has none for the current extractor."""
        if str(document.extra.get("format", "")) != "pdf":
            return False
        if self._documents.has_bibliography(document.id, version=BIBLIOGRAPHY_VERSION):
            return False
        try:
            raw = await connector.fetch(document.source_id)
        except Exception:
            return False
        record = await self._bibliography(document, raw.content)
        if record is None:
            return False
        self._documents.set_bibliography(document.id, record)
        return True

    async def _bibliography(self, document, content: bytes) -> dict[str, object] | None:
        if str(document.extra.get("format", "")) != "pdf":
            return None
        return await asyncio.to_thread(read_bibliography, content)

    async def _embed_pending(self, progress: IndexProgress, tick: Callable[[], None]) -> int:
        pending = self._pending_chunk_ids()
        if not pending:
            return 0
        done = 0
        batch = 64
        for start in range(0, len(pending), batch):
            window = pending[start : start + batch]
            chunks = self._documents.chunks_by_id(window)
            ordered = [chunks[chunk_id] for chunk_id in window if chunk_id in chunks]
            if not ordered:
                continue
            vectors = await self._embedder.embed([chunk.text for chunk in ordered])
            self._vectors.upsert([chunk.id for chunk in ordered], vectors)
            done += len(ordered)
            progress.chunks_embedded = done
            tick()
        return done

    def _pending_chunk_ids(self) -> list[str]:
        everything = self._documents.indexed()
        ids: list[str] = []
        for doc_id in everything:
            ids.extend(self._documents.chunk_ids_for(doc_id))
        return self._vectors.missing(ids)


def summarize(runs: Sequence[IndexProgress]) -> dict[str, object]:
    latest = runs[-1] if runs else None
    return latest.snapshot() if latest else {"status": "idle"}
