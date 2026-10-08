"""Build and inspect the search index, and query it directly."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.interfaces.http.deps import Engine, get_engine

router = APIRouter()


class IndexRequest(BaseModel):
    force: bool = False


class SearchRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    top_k: int | None = None


class SearchHit(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    section: str | None
    page: int
    text: str
    score: float
    found_by: str
    locator: dict[str, object]


@router.post("/index")
async def start_index(
    body: IndexRequest | None = None,
    engine: Engine = Depends(get_engine),
) -> dict[str, object]:
    return engine.start_index(force=bool(body and body.force))


@router.post("/index/cancel")
async def cancel_index(engine: Engine = Depends(get_engine)) -> dict[str, object]:
    return engine.cancel_index()


@router.get("/index/status")
async def index_status(engine: Engine = Depends(get_engine)) -> dict[str, object]:
    return engine.index_status()


@router.post("/search")
async def search(
    body: SearchRequest,
    engine: Engine = Depends(get_engine),
) -> list[SearchHit]:
    """Retrieval without the model, for checking what the index actually holds."""
    hits = await engine.retriever.search(
        body.query,
        sources=list(body.sources) if body.sources else None,
        top_k=body.top_k,
    )
    documents = engine.documents.documents_by_id([hit.chunk.doc_id for hit in hits])
    return [
        SearchHit(
            doc_id=hit.chunk.doc_id,
            chunk_id=hit.chunk.id,
            title=(
                documents[hit.chunk.doc_id].title
                if hit.chunk.doc_id in documents
                else hit.chunk.doc_id
            ),
            section=hit.chunk.section_path,
            page=hit.chunk.page_start,
            text=hit.chunk.text,
            score=round(hit.score, 6),
            found_by=hit.found_by,
            locator=hit.chunk.locator,
        )
        for hit in hits
    ]
