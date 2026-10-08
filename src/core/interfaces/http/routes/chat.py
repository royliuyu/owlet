"""Chat stream: retrieve, then answer over what was retrieved."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core.domain.chat import ChatRequest
from core.domain.models import Chunk
from core.interfaces.http.deps import Engine, get_engine
from core.retrieval.answer import carried_prior, citation_for_document
from core.retrieval.focus import decide, metadata_answer
from core.retrieval.hybrid import Retrieved
from core.retrieval.phrase import anchors, choose_page, contains_anchor, matching, probes
from core.retrieval.records import records_answer, select_records
from core.store import IndexedDocument

router = APIRouter()


@router.post("/chat")
async def chat(body: ChatRequest, engine: Engine = Depends(get_engine)) -> StreamingResponse:
    message_id = uuid.uuid4().hex

    async def events() -> AsyncIterator[str]:
        started = time.perf_counter()
        yield _frame("start", {"message_id": message_id})
        try:
            decision = decide(
                body.question,
                focus_doc_id=body.focus_doc_id,
                papers=engine.documents.papers(),
            )
            if decision.kind == "records" and decision.people:
                async for frame in _from_records(
                    engine,
                    decision.people,
                    list(body.sources) if body.sources else None,
                    started,
                ):
                    yield frame
                return
            if decision.kind == "metadata" and decision.doc_ids and decision.field:
                async for frame in _from_record(
                    engine,
                    decision.doc_ids[0],
                    decision.field,
                    started,
                    index=decision.author_index,
                ):
                    yield frame
                    if frame.startswith("event: done"):
                        return
            scope = list(decision.doc_ids) or None
            asked = _search_question(body.question, body.prior_question)
            needles = anchors(asked)
            yield _frame("tool", {"tool": "search_knowledge", "status": "running"})
            if decision.page and scope:
                hits = _hits_for_page(
                    engine,
                    scope,
                    decision.page,
                    needles,
                    sources=list(body.sources) if body.sources else None,
                )
            else:
                hits = await engine.retriever.search(
                    asked,
                    sources=list(body.sources) if body.sources else None,
                    doc_ids=scope,
                )
            yield _frame(
                "tool",
                {"tool": "search_knowledge", "status": "done", "hits": len(hits)},
            )
            if not hits:
                missing = (
                    f"Page {decision.page} of that document is not in the index."
                    if decision.page and scope
                    else _nothing_found(engine, scoped=scope is not None)
                )
                yield _frame("error", {"message": missing})
                yield _frame("done", {"latency_ms": _elapsed(started)})
                return

            documents = engine.documents.documents_by_id(
                [hit.chunk.doc_id for hit in hits]
            )
            for citation in engine.citations_for(hits, documents):
                yield _frame("citation", citation.model_dump(mode="json"))
            async for piece in engine.stream_answer(
                body.question, hits, documents, prior_question=body.prior_question
            ):
                yield _frame("delta", {"text": piece})
        except Exception as exc:
            yield _frame("error", {"message": str(exc) or "Could not answer that"})
        yield _frame("done", {"latency_ms": _elapsed(started)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _from_records(
    engine: Engine,
    people: tuple[str, ...],
    sources: list[str] | None,
    started: float,
) -> AsyncIterator[str]:
    """Answer from the names stored on each document, one citation per document."""
    matched = select_records(engine.documents.papers(), people, sources=sources)
    yield _frame("tool", {"tool": "list_records", "status": "running"})
    yield _frame(
        "tool",
        {"tool": "list_records", "status": "done", "hits": len(matched)},
    )
    for number, document in enumerate(matched, start=1):
        citation = citation_for_document(document, snippet=_record_snippet(document))
        yield _frame("citation", citation.model_copy(update={"n": number}).model_dump(mode="json"))
    yield _frame("delta", {"text": records_answer(people, matched)})
    yield _frame("done", {"latency_ms": _elapsed(started)})


def _search_question(question: str, prior: str | None) -> str:
    """A follow-up such as "search it again" still retrieves the earlier part name."""
    earlier = carried_prior(question, prior)
    if not earlier:
        return question
    return f"{earlier}\n{question}"


def _hits_for_page(
    engine: Engine,
    doc_ids: list[str],
    page: int,
    needles: tuple[str, ...],
    *,
    sources: list[str] | None,
) -> list[Retrieved]:
    """The named page, or any source's passage on that page that has the phrase."""
    focused = _page_chunks(engine, doc_ids, page)
    wider = focused
    if needles and not any(contains_anchor(chunk.text, needles) for chunk in focused):
        found = engine.documents.chunks_containing(
            probes(needles), sources=sources, page=page, limit=40
        )
        wider = focused + matching(found, needles)
    return _as_hits(choose_page(focused, wider, needles))


def _page_chunks(engine: Engine, doc_ids: list[str], page: int) -> list[Chunk]:
    found: list[Chunk] = []
    for doc_id in doc_ids:
        found.extend(engine.documents.chunks_on_page(doc_id, page))
    return found


def _as_hits(chunks: list[Chunk]) -> list[Retrieved]:
    return [
        Retrieved(chunk=chunk, score=0.0, keyword_rank=rank, vector_rank=None)
        for rank, chunk in enumerate(chunks, start=1)
    ]


def _record_snippet(document: IndexedDocument) -> str:
    if document.authors:
        line = "Authors: " + ", ".join(document.authors)
    else:
        line = document.title
    if document.year:
        line += f" ({document.year})"
    return line


async def _from_record(
    engine: Engine,
    doc_id: str,
    field: str,
    started: float,
    *,
    index: int | None = None,
) -> AsyncIterator[str]:
    """Answer author, year, venue, DOI, or title from this paper, not the library.

    A filled record becomes one sentence. An empty field is read from the
    first page of this paper. Yields nothing when that page is not indexed,
    so the caller can search the same paper.
    """
    documents = engine.documents.documents_by_id([doc_id])
    document = documents.get(doc_id)
    if document is None:
        return
    sentence = metadata_answer(document, field, index=index)
    hits: list[Retrieved] = []
    if sentence is None:
        opening = engine.documents.opening_chunks(doc_id)
        hits = [
            Retrieved(chunk=chunk, score=0.0, keyword_rank=rank, vector_rank=None)
            for rank, chunk in enumerate(opening, start=1)
        ]
        if not hits:
            return
    yield _frame("tool", {"tool": "search_knowledge", "status": "running"})
    yield _frame(
        "tool",
        {"tool": "search_knowledge", "status": "done", "hits": 1 if sentence else len(hits)},
    )
    if sentence is not None:
        citation = citation_for_document(document, snippet=sentence)
        yield _frame("citation", citation.model_dump(mode="json"))
        yield _frame("delta", {"text": sentence})
        yield _frame("done", {"latency_ms": _elapsed(started)})
        return
    for citation in engine.citations_for(hits, documents):
        yield _frame("citation", citation.model_dump(mode="json"))
    async for piece in engine.stream_answer(_field_question(field), hits, documents):
        yield _frame("delta", {"text": piece})
    yield _frame("done", {"latency_ms": _elapsed(started)})


def _field_question(field: str) -> str:
    """The page-1 fallback should be asked the field, not the raw follow-up."""
    asked = {
        "authors": "Who are the authors of this paper?",
        "year": "What year was this paper published?",
        "venue": "Where was this paper published?",
        "doi": "What is the DOI of this paper?",
        "title": "What is the title of this paper?",
    }
    return asked.get(field, field)


def _nothing_found(engine: Engine, *, scoped: bool = False) -> str:
    stats = engine.documents.stats()
    if not stats["chunks"]:
        return (
            "Nothing is indexed yet. Add a folder in Settings, then run Index "
            "to make your files searchable."
        )
    if not stats["embedded"]:
        return (
            f"{stats['chunks']} passages are indexed but none are embedded yet. "
            "Finish the index run, then ask again."
        )
    if scoped:
        return "No passage in this paper matched that question."
    return "No passage in your library matched that question."


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _frame(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
