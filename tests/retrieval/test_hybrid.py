"""One document may not take every passage slot while others are waiting."""

import asyncio
from pathlib import Path

from tests.store.test_scope import _index

from core.config import RetrievalSettings
from core.domain.models import Chunk
from core.retrieval.hybrid import Retrieved, Retriever, _diversify, _order_with_anchor
from core.store import DocumentStore


def test_other_documents_are_seated_before_a_repeat_from_the_leader() -> None:
    fused = [
        _hit("paper:arod", 0, 8),
        _hit("paper:arod", 1, 7),
        _hit("paper:arod", 2, 6),
        _hit("paper:arod", 3, 5),
        _hit("paper:frames", 0, 4),
        _hit("paper:corun", 0, 3),
    ]

    picked = _diversify(fused, wanted=4, per_doc=2)

    assert [(item.chunk.doc_id, item.chunk.ord) for item in picked] == [
        ("paper:arod", 0),
        ("paper:arod", 1),
        ("paper:frames", 0),
        ("paper:corun", 0),
    ]


def test_a_part_name_is_seated_ahead_of_a_higher_ranked_page() -> None:
    ranked = [
        _hit("paper:manual", 0, 9, "RETURN TO NEUTRAL ASSEMBLY OPTION"),
        _hit("paper:manual", 1, 8, "NEUTRAL-LOCK lever position"),
    ]
    part = _chunk("paper:catalogue", 27, "11 126-8195 1 Spring-Return, Neutral")

    picked = _order_with_anchor(ranked, [part], ("Spring-Return",), limit=2)

    assert [item.chunk.text for item in picked] == [
        "11 126-8195 1 Spring-Return, Neutral",
        "RETURN TO NEUTRAL ASSEMBLY OPTION",
    ]


def test_a_single_matching_document_still_fills_the_window() -> None:
    fused = [_hit("paper:arod", order, 8 - order) for order in range(6)]

    picked = _diversify(fused, wanted=4, per_doc=2)

    assert [item.chunk.ord for item in picked] == [0, 1, 2, 3]


def test_a_stated_count_keeps_the_passage_that_contains_it(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "meta.db")
    _index(store, "paper:arod", "The Lucas-Kanade method and five other machine learning methods")
    _index(store, "paper:manual", "Remove the paper air filter and check the element")
    _index(
        store,
        "paper:hadd",
        "After extending the 12 ML models by applying all of the proposed optimizations",
    )
    retriever = Retriever(
        documents=store,
        vectors=_NoVectors(),
        embedder=_NoEmbedder(),
        settings=RetrievalSettings(),
    )

    hits = asyncio.run(
        retriever.search(
            "there are 12 machine learning models are used in one of the paper, which paper is it?"
        )
    )

    assert hits[0].chunk.doc_id == "paper:hadd"
    assert "12" in hits[0].chunk.text


def test_a_supplied_probe_selects_the_passage(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "meta.db")
    _index(store, "paper:kept", "alpha beta shows 12 cases in the trial")
    _index(store, "paper:other", "12 cases and nothing else about the count of cases")
    retriever = Retriever(
        documents=store,
        vectors=_NoVectors(),
        embedder=_NoEmbedder(),
        settings=RetrievalSettings(),
        parser=_Probes(("alpha beta",)),
    )

    hits = asyncio.run(retriever.search("which paper mentions 12 cases?"))

    assert hits[0].chunk.doc_id == "paper:kept"


class _Probes:
    def __init__(self, probes: tuple[str, ...]) -> None:
        self._probes = probes

    async def probes(self, question: str, *, titles: list[str]) -> tuple[str, ...]:
        return self._probes


class _NoVectors:
    def search(self, vector: list[float], *, limit: int) -> list[object]:
        return []

    def search_among(
        self, vector: list[float], chunk_ids: list[str], *, limit: int
    ) -> list[object]:
        return []


class _NoEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


def _hit(doc_id: str, order: int, score: float, text: str = "passage") -> Retrieved:
    return Retrieved(
        chunk=_chunk(doc_id, order, text),
        score=score,
        keyword_rank=order + 1,
        vector_rank=None,
    )


def _chunk(doc_id: str, order: int, text: str) -> Chunk:
    return Chunk(id=f"{doc_id}:{order}", doc_id=doc_id, ord=order, text=text)
