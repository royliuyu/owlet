"""Vector index.

Everything specific to sqlite-vec is in `SqliteVecStore`. Callers see
only `VectorStore`, and chunk ids are the sole currency crossing that
line, so moving to Chroma, Qdrant, or pgvector means writing one class
and re-running the embed pass. No text or provenance lives here: losing
this table costs compute, never content.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from core.store.db import migrate, session


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: str
    score: float  # higher is nearer


class VectorStore(Protocol):
    model: str
    dim: int

    def upsert(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None: ...

    def search(self, vector: Sequence[float], *, limit: int) -> list[VectorHit]: ...

    def search_among(
        self, vector: Sequence[float], chunk_ids: Sequence[str], *, limit: int
    ) -> list[VectorHit]: ...

    def delete(self, chunk_ids: Sequence[str]) -> None: ...

    def missing(self, chunk_ids: Sequence[str]) -> list[str]: ...


class SqliteVecStore:
    """Vectors in the same file as the metadata, via the sqlite-vec extension."""

    def __init__(self, db_path: Path, *, model: str, dim: int) -> None:
        self._db_path = db_path
        self.model = model
        self.dim = dim
        self._ready = False

    def upsert(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunk_ids) != len(vectors):
            raise ValueError("chunk_ids and vectors must be the same length")
        if not chunk_ids:
            return
        created = datetime.now(tz=timezone.utc).isoformat()
        with self._session() as connection:
            connection.executemany(
                "DELETE FROM vec_chunks WHERE chunk_id = ?",
                [(chunk_id,) for chunk_id in chunk_ids],
            )
            connection.executemany(
                "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                [
                    (chunk_id, _pack(vector, self.dim))
                    for chunk_id, vector in zip(chunk_ids, vectors)
                ],
            )
            connection.executemany(
                "INSERT INTO embeddings (chunk_id, model, dim, created_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(chunk_id, model) DO UPDATE SET"
                " dim=excluded.dim, created_at=excluded.created_at",
                [(chunk_id, self.model, self.dim, created) for chunk_id in chunk_ids],
            )

    def search(self, vector: Sequence[float], *, limit: int) -> list[VectorHit]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT chunk_id, distance FROM vec_chunks"
                " WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (_pack(vector, self.dim), limit),
            ).fetchall()
        return [VectorHit(chunk_id=row["chunk_id"], score=-float(row["distance"])) for row in rows]

    def search_among(
        self, vector: Sequence[float], chunk_ids: Sequence[str], *, limit: int
    ) -> list[VectorHit]:
        """Nearest of these chunks only.

        A library-wide nearest-neighbour query filtered afterwards drops the
        paper when other documents rank higher. One paper is a few dozen
        vectors, so the distance is computed over that set directly.
        """
        if not chunk_ids or limit <= 0:
            return []
        query = _pack(vector, self.dim)
        marks = ",".join("?" for _ in chunk_ids)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT chunk_id, embedding FROM vec_chunks WHERE chunk_id IN ({marks})",
                tuple(chunk_ids),
            ).fetchall()
        scored = [
            VectorHit(chunk_id=row["chunk_id"], score=-_l2(query, bytes(row["embedding"])))
            for row in rows
            if row["embedding"] is not None
        ]
        scored.sort(key=lambda hit: -hit.score)
        return scored[:limit]

    def delete(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        with self._session() as connection:
            connection.executemany(
                "DELETE FROM vec_chunks WHERE chunk_id = ?",
                [(chunk_id,) for chunk_id in chunk_ids],
            )
            connection.executemany(
                "DELETE FROM embeddings WHERE chunk_id = ? AND model = ?",
                [(chunk_id, self.model) for chunk_id in chunk_ids],
            )

    def missing(self, chunk_ids: Sequence[str]) -> list[str]:
        """Which of these have no vector from the current model yet."""
        if not chunk_ids:
            return []
        marks = ",".join("?" for _ in chunk_ids)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT chunk_id FROM embeddings"
                f" WHERE model = ? AND chunk_id IN ({marks})",
                (self.model, *chunk_ids),
            ).fetchall()
        done = {row["chunk_id"] for row in rows}
        return [chunk_id for chunk_id in chunk_ids if chunk_id not in done]

    def _session(self):
        if not self._ready:
            migrate(self._db_path, embedding_dim=self.dim)
            self._ready = True
        return session(self._db_path)


def _pack(vector: Sequence[float], dim: int) -> bytes:
    if len(vector) != dim:
        raise ValueError(f"expected a {dim}-dimension vector, got {len(vector)}")
    return struct.pack(f"{dim}f", *vector)


def _l2(left: bytes, right: bytes) -> float:
    width = len(left) // 4
    if width == 0 or len(right) != len(left):
        return float("inf")
    a = struct.unpack(f"{width}f", left)
    b = struct.unpack(f"{width}f", right)
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
