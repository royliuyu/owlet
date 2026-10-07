"""One document: extracted pages for the viewer, or the original bytes."""

from __future__ import annotations

import asyncio
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from core.domain.errors import InvalidSourceIdError
from core.domain.models import Document, SourceKind
from core.ingestion.parse.base import PageText, PreviewBlock
from core.ingestion.preview import preview_document
from core.interfaces.http.deps import connector_for, get_sources
from core.store import SourceStore

router = APIRouter()

_KINDS = {"paper", "note", "email", "event", "file", "task"}


class DocumentPreview(BaseModel):
    document: Document
    pages: list[PageText]
    blocks: list[PreviewBlock] = Field(default_factory=list)


@router.get("/documents/{doc_id:path}", response_model=None)
async def get_document(
    doc_id: str,
    store: SourceStore = Depends(get_sources),
    view: Literal["meta", "file"] = Query(default="meta"),
) -> DocumentPreview | Response:
    connector = connector_for(store)
    if connector is None:
        raise HTTPException(status_code=404, detail="No collections configured")
    kind, source_id = _split_document_id(doc_id)
    raw = await connector.fetch(source_id)
    if raw.source != kind:
        raise InvalidSourceIdError(doc_id)
    if view == "file":
        filename = quote(f"{raw.title}{_suffix(raw.media_type)}")
        return Response(
            content=raw.content,
            media_type=raw.media_type,
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
                "Cache-Control": "private, max-age=60",
            },
        )
    document = connector.to_document(raw)
    parsed = await asyncio.to_thread(preview_document, raw)
    return DocumentPreview(document=document, pages=parsed.pages, blocks=parsed.preview)


@router.post("/actions/{action_id}/confirm")
async def confirm_action(action_id: str) -> JSONResponse:
    return JSONResponse(
        {
            "message": (
                f"Actions are not available yet. Nothing was sent for {action_id}."
            )
        },
        status_code=501,
    )


def _split_document_id(doc_id: str) -> tuple[SourceKind, str]:
    kind, sep, source_id = doc_id.partition(":")
    if sep != ":" or kind not in _KINDS or not source_id:
        raise InvalidSourceIdError(doc_id)
    return kind, source_id  # type: ignore[return-value]


def _suffix(media_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(media_type, "")
