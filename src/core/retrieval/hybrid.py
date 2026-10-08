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
from core.retrieval.phrase import contains_anchor, contains_count, matching, probes
from core.retrieval.understand import ProbeParser, QueryPlan, fallback_plan
from core.store import DocumentStore, ScoredChunk, VectorStore


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
        parser: ProbeParser | None = None,
    ) -> None:
        self._documents = documents
        self._vectors = vectors
        self._embedder = embedder
        self._settings = settings
        self._parser = parser

    async def search(
        self,
        question: str,
        *,
        sources: list[str] | None = None,
        doc_ids: Sequence[str] | None = None,
        top_k: int | None = None,
    ) -> list[Retrieved]:
        wanted = top_k or self._settings.top_k
        plan = await self._plan(question)
        keyword_ranks, pool, from_probe = self._keywords(
            plan.probes, sources=sources, doc_ids=doc_ids
        )
        if plan.counts and plan.literal is None:
            self._counts_into(plan.counts, keyword_ranks, pool, sources=sources, doc_ids=doc_ids)

        vector_ranks = await self._vectors_for(
            plan.probes, pool, from_probe, sources=sources, doc_ids=doc_ids
        )

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
        fused.sort(
            key=lambda item: (
                _tier(item, plan, from_probe),
                -item.score,
                item.chunk.doc_id,
                item.chunk.ord,
            )
        )
        ranked = _diversify(fused, wanted, self._settings.per_doc_k)
        if not plan.literal:
            return ranked
        needles = (plan.literal,)
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

    async def _plan(self, question: str) -> QueryPlan:
        plan = fallback_plan(question)
        if plan.literal is not None or self._parser is None:
            return plan
        try:
            titles = [paper.title for paper in self._documents.papers()]
            extra = await self._parser.probes(question, titles=titles)
        except Exception:
            return plan
        return QueryPlan(_merge_probes(plan.probes, extra), plan.counts, plan.literal)

    def _keywords(
        self,
        phrases: Sequence[str],
        *,
        sources: list[str] | None,
        doc_ids: Sequence[str] | None,
    ) -> tuple[dict[str, int], dict[str, Chunk], set[str]]:
        ranks: dict[str, int] = {}
        pool: dict[str, Chunk] = {}
        for phrase in phrases:
            hits = self._documents.search_fulltext(
                phrase, limit=self._settings.bm25_k, sources=sources, doc_ids=doc_ids
            )
            _keep_best(hits, ranks, pool)
        return ranks, pool, set(ranks)

    def _counts_into(
        self,
        numbers: Sequence[str],
        ranks: dict[str, int],
        pool: dict[str, Chunk],
        *,
        sources: list[str] | None,
        doc_ids: Sequence[str] | None,
    ) -> None:
        """Pull passages that state the number in, behind any probe hit."""
        behind = self._settings.bm25_k
        for number in numbers:
            hits = self._documents.search_fulltext(
                number, limit=self._settings.bm25_k, sources=sources, doc_ids=doc_ids
            )
            _keep_best(hits, ranks, pool, offset=behind)

    async def _vectors_for(
        self,
        phrases: Sequence[str],
        pool: dict[str, Chunk],
        from_probe: set[str],
        *,
        sources: list[str] | None,
        doc_ids: Sequence[str] | None,
    ) -> dict[str, int]:
        ranks: dict[str, int] = {}
        if not phrases or not self._documents.stats()["embedded"]:
            return ranks
        try:
            embedded = await self._embedder.embed(list(phrases))
        except Exception:
            return ranks  # model host down; keyword results still stand
        allowed: list[str] | None = None
        if doc_ids:
            allowed = []
            for doc_id in doc_ids:
                allowed.extend(self._documents.chunk_ids_for(doc_id))
        for vector in embedded:
            if allowed is not None:
                hits = self._vectors.search_among(vector, allowed, limit=self._settings.vector_k)
            else:
                hits = self._vectors.search(vector, limit=self._settings.vector_k)
            missing = [hit.chunk_id for hit in hits if hit.chunk_id not in pool]
            loaded = self._documents.chunks_by_id(missing)
            for rank, hit in enumerate(hits, start=1):
                chunk = pool.get(hit.chunk_id) or loaded.get(hit.chunk_id)
                if chunk is None:
                    continue
                if sources and chunk.doc_id.split(":", 1)[0] not in sources:
                    continue
                pool.setdefault(chunk.id, chunk)
                from_probe.add(chunk.id)
                current = ranks.get(chunk.id)
                if current is None or rank < current:
                    ranks[chunk.id] = rank
        return ranks


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


def _merge_probes(base: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for probe in (*base, *extra):
        key = " ".join(probe.split()).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(" ".join(probe.split()))
        if len(merged) == 4:
            break
    return tuple(merged)


def _keep_best(
    hits: Sequence[ScoredChunk],
    ranks: dict[str, int],
    pool: dict[str, Chunk],
    *,
    offset: int = 0,
) -> None:
    for rank, hit in enumerate(hits, start=1):
        pool.setdefault(hit.chunk.id, hit.chunk)
        position = offset + rank
        current = ranks.get(hit.chunk.id)
        if current is None or position < current:
            ranks[hit.chunk.id] = position


def _tier(item: Retrieved, plan: QueryPlan, from_probe: set[str]) -> int:
    """Probe hits that also state the count, then other probe hits, then the count alone."""
    if not plan.counts or plan.literal is not None:
        return 0
    stated = contains_count(item.chunk.text, plan.counts)
    if item.chunk.id in from_probe and stated:
        return 0
    if item.chunk.id in from_probe:
        return 1
    return 2


def _rrf(rank: int | None, k: int) -> float:
    return 0.0 if rank is None else 1.0 / (k + rank)
