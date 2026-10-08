"""Documents, chunks, and full-text search.

Chunk text lives here and nowhere else. `search_fulltext` is the only
place FTS5 syntax appears, so a different full-text engine would replace
one method.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.domain.models import BBox, Chunk, Document
from core.store.db import migrate, session


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    id: str
    title: str
    uri: str
    source: str
    collection: str | None
    content_hash: str
    chunking_version: str
    indexed_at: datetime | None
    filename: str = ""
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str = ""
    doi: str = ""


class DocumentStore:
    def __init__(self, db_path: Path, *, embedding_dim: int | None = None) -> None:
        self._db_path = db_path
        self._embedding_dim = embedding_dim
        self._ready = False

    def upsert_document(
        self,
        document: Document,
        *,
        root_id: str,
        page_count: int,
        parser: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "INSERT INTO documents (id, source, source_id, root_id, title, uri,"
                " collection, created_at, updated_at, content_hash, page_count,"
                " extra_json, indexed_at, parser, deleted_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)"
                " ON CONFLICT(id) DO UPDATE SET"
                " title=excluded.title, uri=excluded.uri, collection=excluded.collection,"
                " updated_at=excluded.updated_at, content_hash=excluded.content_hash,"
                " page_count=excluded.page_count, extra_json=excluded.extra_json,"
                " indexed_at=excluded.indexed_at, parser=excluded.parser, deleted_at=NULL",
                (
                    document.id,
                    document.source,
                    document.source_id,
                    root_id,
                    document.title,
                    document.uri,
                    document.collection,
                    document.created_at.isoformat(),
                    document.updated_at.isoformat(),
                    document.content_hash,
                    page_count,
                    json.dumps(document.extra, ensure_ascii=False, default=str),
                    _now(),
                    parser,
                ),
            )

    def replace_chunks(
        self, doc_id: str, chunks: Sequence[Chunk], *, chunking_version: str
    ) -> list[str]:
        """Swap a document's chunks wholesale. Returns the ids now stored."""
        created = _now()
        with self._session() as connection:
            connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            connection.executemany(
                "INSERT INTO chunks (id, doc_id, ord, text, token_count, char_start,"
                " char_end, page_start, page_end, section_path, section_kind,"
                " bboxes_json, chunking_version, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        chunk.id,
                        chunk.doc_id,
                        chunk.ord,
                        chunk.text,
                        chunk.token_count,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.page_start,
                        chunk.page_end,
                        chunk.section_path,
                        chunk.section_kind,
                        json.dumps([box.model_dump() for box in chunk.bboxes]),
                        chunking_version,
                        created,
                    )
                    for chunk in chunks
                ],
            )
        return [chunk.id for chunk in chunks]

    def has_bibliography(self, doc_id: str, *, version: int) -> bool:
        with self._session() as connection:
            row = connection.execute(
                "SELECT extra_json FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
        if row is None:
            return False
        record = _bibliography(row["extra_json"])
        return record.get("v") == version

    def set_bibliography(self, doc_id: str, record: dict[str, object]) -> None:
        """Merge a paper record into extra_json. Chunks stay as they are."""
        with self._session() as connection:
            row = connection.execute(
                "SELECT extra_json FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                return
            try:
                extra = json.loads(row["extra_json"] or "{}")
            except json.JSONDecodeError:
                extra = {}
            if not isinstance(extra, dict):
                extra = {}
            extra["bibliography"] = record
            connection.execute(
                "UPDATE documents SET extra_json = ? WHERE id = ?",
                (json.dumps(extra, ensure_ascii=False), doc_id),
            )

    def indexed(self) -> dict[str, IndexedDocument]:
        """What is already in the index, keyed by document id."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT d.id, d.title, d.uri, d.source, d.collection, d.content_hash,"
                " d.indexed_at,"
                " (SELECT c.chunking_version FROM chunks c WHERE c.doc_id = d.id LIMIT 1)"
                " AS chunking_version"
                " FROM documents d WHERE d.deleted_at IS NULL"
            ).fetchall()
        return {
            row["id"]: IndexedDocument(
                id=row["id"],
                title=row["title"],
                uri=row["uri"],
                source=row["source"],
                collection=row["collection"],
                content_hash=row["content_hash"],
                chunking_version=row["chunking_version"] or "",
                indexed_at=_parse(row["indexed_at"]),
            )
            for row in rows
        }

    def delete_documents(self, doc_ids: Sequence[str]) -> list[str]:
        """Remove documents and their chunks. Returns the orphaned chunk ids."""
        if not doc_ids:
            return []
        marks = ",".join("?" for _ in doc_ids)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT id FROM chunks WHERE doc_id IN ({marks})", tuple(doc_ids)
            ).fetchall()
            connection.execute(
                f"DELETE FROM documents WHERE id IN ({marks})", tuple(doc_ids)
            )
        return [row["id"] for row in rows]

    def delete_root(self, root_id: str) -> list[str]:
        """Remove every document filed under one folder. Returns orphaned chunk ids.

        The folder is the unit that stays gone: a file deleted on its own is
        still inside an enabled folder, so the next index would write it back.
        """
        with self._session() as connection:
            rows = connection.execute(
                "SELECT c.id FROM chunks c"
                " JOIN documents d ON d.id = c.doc_id"
                " WHERE d.root_id = ?",
                (root_id,),
            ).fetchall()
            connection.execute("DELETE FROM documents WHERE root_id = ?", (root_id,))
        return [row["id"] for row in rows]

    def papers(self) -> list[IndexedDocument]:
        """Every live document, with the stored paper record attached."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT id, title, uri, source, collection, content_hash, indexed_at,"
                " extra_json FROM documents WHERE deleted_at IS NULL"
            ).fetchall()
        return [_indexed(row, with_record=True) for row in rows]

    def chunks_containing(
        self,
        needles: Sequence[str],
        *,
        doc_ids: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        page: int | None = None,
        limit: int = 8,
    ) -> list[Chunk]:
        """Passages that contain one of these strings, in any source kind."""
        terms = [needle.casefold() for needle in needles if needle.strip()]
        if not terms or (doc_ids is not None and not doc_ids):
            return []
        marks = " OR ".join("instr(lower(c.text), ?) > 0" for _ in terms)
        sql = (
            "SELECT c.* FROM chunks c"
            " JOIN documents d ON d.id = c.doc_id"
            f" WHERE d.deleted_at IS NULL AND ({marks})"
        )
        params: list[object] = list(terms)
        if sources:
            sql += f" AND d.source IN ({','.join('?' for _ in sources)})"
            params.extend(sources)
        if doc_ids is not None:
            sql += f" AND c.doc_id IN ({','.join('?' for _ in doc_ids)})"
            params.extend(doc_ids)
        if page is not None:
            sql += " AND c.page_start <= ? AND c.page_end >= ?"
            params.extend((page, page))
        sql += " ORDER BY c.doc_id, c.ord LIMIT ?"
        params.append(limit)
        with self._session() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [_chunk(row) for row in rows]

    def chunks_on_page(self, doc_id: str, page: int) -> list[Chunk]:
        """Passages that cover this page, in reading order."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE doc_id = ? AND page_start <= ? AND page_end >= ?"
                " ORDER BY ord",
                (doc_id, page, page),
            ).fetchall()
        return [_chunk(row) for row in rows]

    def opening_chunks(self, doc_id: str, *, limit: int = 3) -> list[Chunk]:
        """The first page, for a metadata question the record could not answer."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE doc_id = ? AND page_start = 1"
                " ORDER BY ord LIMIT ?",
                (doc_id, limit),
            ).fetchall()
        return [_chunk(row) for row in rows]

    def chunk_ids_for(self, doc_id: str) -> list[str]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT id FROM chunks WHERE doc_id = ? ORDER BY ord", (doc_id,)
            ).fetchall()
        return [row["id"] for row in rows]

    def chunks_by_id(self, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" for _ in chunk_ids)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM chunks WHERE id IN ({marks})", tuple(chunk_ids)
            ).fetchall()
        return {row["id"]: _chunk(row) for row in rows}

    def documents_by_id(self, doc_ids: Sequence[str]) -> dict[str, IndexedDocument]:
        if not doc_ids:
            return {}
        marks = ",".join("?" for _ in doc_ids)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT id, title, uri, source, collection, content_hash, indexed_at,"
                f" extra_json FROM documents WHERE id IN ({marks})",
                tuple(doc_ids),
            ).fetchall()
        return {row["id"]: _indexed(row, with_record=True) for row in rows}

    def search_fulltext(
        self,
        query: str,
        *,
        limit: int,
        sources: Sequence[str] | None = None,
        doc_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        """BM25 over chunk text. Returns best-first; score is higher-is-better."""
        return self._match(_fts_query(query), limit=limit, sources=sources, doc_ids=doc_ids)

    def _match(
        self,
        match: str,
        *,
        limit: int,
        sources: Sequence[str] | None,
        doc_ids: Sequence[str] | None,
    ) -> list[ScoredChunk]:
        if not match:
            return []
        sql = (
            "SELECT c.*, bm25(chunks_fts) AS rank FROM chunks_fts"
            " JOIN chunks c ON c.rowid = chunks_fts.rowid"
            " JOIN documents d ON d.id = c.doc_id"
            " WHERE chunks_fts MATCH ? AND d.deleted_at IS NULL"
        )
        params: list[object] = [match]
        if sources:
            sql += f" AND d.source IN ({','.join('?' for _ in sources)})"
            params.extend(sources)
        if doc_ids:
            sql += f" AND c.doc_id IN ({','.join('?' for _ in doc_ids)})"
            params.extend(doc_ids)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._session() as connection:
            try:
                rows = connection.execute(sql, tuple(params)).fetchall()
            except sqlite3.OperationalError:
                return []  # the query was not valid FTS5 syntax
        return [ScoredChunk(chunk=_chunk(row), score=-float(row["rank"])) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._session() as connection:
            documents = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
            ).fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            embedded = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        return {"documents": documents, "chunks": chunks, "embedded": embedded}

    def _session(self):
        if not self._ready:
            migrate(self._db_path, embedding_dim=self._embedding_dim)
            self._ready = True
        return session(self._db_path)


def _indexed(row: sqlite3.Row, *, with_record: bool) -> IndexedDocument:
    record = _bibliography(row["extra_json"]) if with_record else {}
    filename = row["title"]
    display = str(record.get("title") or "").strip() or filename
    raw_authors = record.get("authors")
    authors = (
        tuple(str(name) for name in raw_authors if str(name).strip())
        if isinstance(raw_authors, list)
        else ()
    )
    year = record.get("year")
    return IndexedDocument(
        id=row["id"],
        title=display,
        uri=row["uri"],
        source=row["source"],
        collection=row["collection"],
        content_hash=row["content_hash"],
        chunking_version=row["chunking_version"] if "chunking_version" in row.keys() else "",
        indexed_at=_parse(row["indexed_at"]),
        filename=filename,
        authors=authors,
        year=year if isinstance(year, int) else None,
        venue=str(record.get("venue") or ""),
        doi=str(record.get("doi") or ""),
    )


def _bibliography(extra_json: str) -> dict[str, object]:
    try:
        extra = json.loads(extra_json or "{}")
    except json.JSONDecodeError:
        return {}
    record = extra.get("bibliography") if isinstance(extra, dict) else None
    return record if isinstance(record, dict) else {}


def _chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=row["id"],
        doc_id=row["doc_id"],
        ord=row["ord"],
        text=row["text"],
        token_count=row["token_count"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        section_path=row["section_path"],
        section_kind=row["section_kind"],
        bboxes=[BBox(**box) for box in json.loads(row["bboxes_json"] or "[]")],
        char_start=row["char_start"],
        char_end=row["char_end"],
    )


def _fts_query(query: str) -> str:
    """Quote every term so user punctuation cannot be read as FTS5 syntax."""
    terms = [term for term in _words(query) if term]
    return " OR ".join(f'"{term}"' for term in terms)


def _words(query: str) -> list[str]:
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in query)
    return [word for word in cleaned.split() if len(word) > 1]


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
