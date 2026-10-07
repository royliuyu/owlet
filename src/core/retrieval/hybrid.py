"""Keyword and vector search, fused by reciprocal rank.

BM25 catches the exact term a paper uses; the vector catches the phrasing
it does not. RRF merges them on rank alone, so neither has to produce
scores on a comparable scale, and one engine being absent (no vectors
embedded yet, or a query FTS5 cannot parse) degrades the result instead
of emptying it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.config import RetrievalSettings
from core.domain.models import Chunk
from core.llm import EmbeddingClient
from core.retrieval.phrase import anchors, contains_anchor, matching, probes
from core.store import DocumentStore, VectorStore


@dataclass(frozen=True, slots=True)
class Retrieved:
    chunk: Chunk
    score: float
    keyword_rank: int | None
    vector_rank: int | None

    @property
    def found_by(self) -> str:
        if self.keyword_rank is not None and self.vector_rank is not None:
            return "both"
        return "keyword" if self.keyword_rank is not None else "vector"


class Retriever:
    def __init__(
        self,
        *,
        documents: DocumentStore,
        vectors: VectorStore,
        embedder: EmbeddingClient,
        settings: RetrievalSettings,
    ) -> None:
        self._documents = documents
        self._vectors = vectors
        self._embedder = embedder
        self._settings = settings

    async def search(
        self,
        question: str,
        *,
        sources: list[str] | None = None,
        doc_ids: Sequence[str] | None = None,
        top_k: int | None = None,
    ) -> list[Retrieved]:
        wanted = top_k or self._settings.top_k
        keyword = self._documents.search_fulltext(
            question, limit=self._settings.bm25_k, sources=sources, doc_ids=doc_ids
        )
        keyword_ranks = {hit.chunk.id: rank for rank, hit in enumerate(keyword, start=1)}
        pool: dict[str, Chunk] = {hit.chunk.id: hit.chunk for hit in keyword}

        vector_ranks: dict[str, int] = {}
        embedded: list[list[float]] = []
        if self._documents.stats()["embedded"]:
            try:
                embedded = await self._embedder.embed([question])
            except Exception:
                embedded = []  # model host down; keyword results still stand
        if embedded:
            if doc_ids:
                allowed: list[str] = []
                for doc_id in doc_ids:
                    allowed.extend(self._documents.chunk_ids_for(doc_id))
                hits = self._vectors.search_among(
                    embedded[0], allowed, limit=self._settings.vector_k
                )
            else:
                hits = self._vectors.search(embedded[0], limit=self._settings.vector_k)
            vector_ranks = {hit.chunk_id: rank for rank, hit in enumerate(hits, start=1)}
            missing = [hit.chunk_id for hit in hits if hit.chunk_id not in pool]
            pool.update(self._documents.chunks_by_id(missing))

        fused: list[Retrieved] = []
        for chunk_id, chunk in pool.items():
            keyword_rank = keyword_ranks.get(chunk_id)
            vector_rank = vector_ranks.get(chunk_id)
            if keyword_rank is None and vector_rank is None:
                continue
            if sources and chunk.doc_id.split(":", 1)[0] not in sources:
                continue
            if doc_ids and chunk.doc_id not in doc_ids:
                continue
            fused.append(
                Retrieved(
                    chunk=chunk,
                    score=_rrf(keyword_rank, self._settings.rrf_k)
                    + _rrf(vector_rank, self._settings.rrf_k),
                    keyword_rank=keyword_rank,
                    vector_rank=vector_rank,
                )
            )
        fused.sort(key=lambda item: (-item.score, item.chunk.doc_id, item.chunk.ord))
        ranked = _diversify(fused, wanted, self._settings.per_doc_k)
        needles = anchors(question)
        if not needles:
            return ranked
        found = matching(
            self._documents.chunks_containing(
                probes(needles),
                doc_ids=doc_ids,
                sources=sources,
                limit=max(wanted * 5, wanted),
            ),
            needles,
        )
        return _order_with_anchor(ranked, found, needles, wanted)


def _order_with_anchor(
    ranked: list[Retrieved],
    found: Sequence[Chunk],
    needles: Sequence[str],
    limit: int,
) -> list[Retrieved]:
    """Put passages that contain the part name ahead of the rank list."""
    if not needles or limit < 1:
        return ranked[:limit]
    pinned: list[Retrieved] = []
    seen: set[str] = set()
    for chunk in found:
        if chunk.id in seen or not contains_anchor(chunk.text, needles):
            continue
        seen.add(chunk.id)
        pinned.append(
            Retrieved(chunk=chunk, score=1.0, keyword_rank=len(pinned) + 1, vector_rank=None)
        )
    for hit in ranked:
        if hit.chunk.id in seen or not contains_anchor(hit.chunk.text, needles):
            continue
        seen.add(hit.chunk.id)
        pinned.append(hit)
    rest = [hit for hit in ranked if hit.chunk.id not in seen]
    return (pinned + rest)[:limit]


def _diversify(fused: list[Retrieved], wanted: int, per_doc: int) -> list[Retrieved]:
    """Give each document a turn, then fill any slots still open.

    A library search ranks passages, and one file that repeats a name can
    occupy the whole window. The cap is applied first; passages over the cap
    come back only when nothing else is waiting.
    """
    if per_doc < 1:
        return fused[:wanted]
    picked: list[Retrieved] = []
    overflow: list[Retrieved] = []
    counts: dict[str, int] = {}
    for item in fused:
        doc_id = item.chunk.doc_id
        if counts.get(doc_id, 0) < per_doc:
            picked.append(item)
            counts[doc_id] = counts.get(doc_id, 0) + 1
        else:
            overflow.append(item)
        if len(picked) == wanted:
            return picked
    picked.extend(overflow[: wanted - len(picked)])
    return picked


def _rrf(rank: int | None, k: int) -> float:
    return 0.0 if rank is None else 1.0 / (k + rank)
