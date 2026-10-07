"""Shared request dependencies."""

from __future__ import annotations

from fastapi import Request

from core.config import Settings
from core.connectors.google import GoogleConnector
from core.connectors.local_files import LocalFilesConnector
from core.interfaces.http.engine import Engine
from core.store import SourceStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_sources(request: Request) -> SourceStore:
    return request.app.state.engine.sources


def get_google(request: Request) -> GoogleConnector:
    return request.app.state.engine.google


def connector_for(store: SourceStore) -> LocalFilesConnector | None:
    """A connector over the enabled folders, or None when there are none."""
    from core.connectors.local_files import LocalRoot

    records = store.list(enabled_only=True)
    if not records:
        return None
    return LocalFilesConnector(
        LocalRoot(path=item.path, id=item.id, collection=item.collection)
        for item in records
    )


__all__ = [
    "Engine",
    "connector_for",
    "get_engine",
    "get_google",
    "get_settings",
    "get_sources",
]
