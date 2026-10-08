"""The folders owlet reads, and the files under them.

The folder list is stored in SQLite and edited here, so adding a folder
needs no file on the server and no restart.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from core.connectors.browse import list_folders
from core.domain.errors import SourceNotFoundError
from core.domain.models import SourceKind
from core.interfaces.http.deps import Engine, connector_for, get_engine, get_sources
from core.store import SourceRecord, SourceStore

router = APIRouter()


class CollectionOut(BaseModel):
    id: str
    label: str
    path: str
    enabled: bool


class NewCollection(BaseModel):
    path: str = Field(min_length=1)
    label: str | None = None
    id: str | None = None


class CollectionPatch(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class BrowseEntry(BaseModel):
    name: str
    path: str


class BrowseOut(BaseModel):
    path: str
    parent: str | None
    entries: list[BrowseEntry]


class LibraryFileOut(BaseModel):
    id: str
    source: SourceKind
    source_id: str
    title: str
    uri: str
    collection: str | None
    media_type: str
    updated_at: datetime
    content_hash: str


@router.get("/browse")
def browse_folders(path: str = "") -> BrowseOut:
    """Folders the server can open. An empty path lists the drives."""
    listing = list_folders(path)
    return BrowseOut(
        path=listing.path,
        parent=listing.parent,
        entries=[BrowseEntry(name=item.name, path=item.path) for item in listing.entries],
    )


@router.get("/collections")
async def list_collections(store: SourceStore = Depends(get_sources)) -> list[CollectionOut]:
    return [_out(item) for item in store.list()]


@router.post("/collections", status_code=201)
async def add_collection(
    body: NewCollection,
    store: SourceStore = Depends(get_sources),
) -> CollectionOut:
    try:
        record = store.add(body.path, label=body.label, source_id=body.id)
    except SourceNotFoundError as exc:
        # The folder the user typed does not exist: their input, not a missing route.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(record)


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: str,
    body: CollectionPatch,
    store: SourceStore = Depends(get_sources),
) -> CollectionOut:
    return _out(store.update(collection_id, label=body.label, enabled=body.enabled))


@router.delete("/collections/{collection_id}", status_code=204)
async def remove_collection(
    collection_id: str,
    engine: Engine = Depends(get_engine),
) -> Response:
    if engine.indexing:
        raise HTTPException(
            status_code=409,
            detail="An index run is in progress. Remove the folder after it finishes.",
        )
    if not engine.remove_collection(collection_id):
        raise HTTPException(status_code=404, detail="Unknown collection")
    return Response(status_code=204)


@router.get("/collections/{collection_id}/files")
async def list_files(
    collection_id: str,
    store: SourceStore = Depends(get_sources),
) -> list[LibraryFileOut]:
    record = store.get(collection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown collection")
    connector = connector_for(store)
    if connector is None or not record.enabled:
        return []
    documents = await connector.list_documents()
    return [
        LibraryFileOut(
            id=doc.id,
            source=doc.source,
            source_id=doc.source_id,
            title=doc.title,
            uri=doc.uri,
            collection=doc.collection,
            media_type=str(doc.extra.get("media_type", "")),
            updated_at=doc.updated_at,
            content_hash=doc.content_hash,
        )
        for doc in documents
        if doc.extra.get("root_id") == collection_id
    ]


def _out(record: SourceRecord) -> CollectionOut:
    return CollectionOut(
        id=record.id,
        label=record.collection,
        path=str(record.path),
        enabled=record.enabled,
    )
