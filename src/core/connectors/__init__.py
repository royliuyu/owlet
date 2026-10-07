"""Data-source adapters. One module per source, one protocol."""

from core.connectors.base import Change, ChangeSet, Connector, RawDocument
from core.connectors.local_files import (
    SUPPORTED_SUFFIXES,
    LocalFilesConnector,
    LocalRoot,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "Change",
    "ChangeSet",
    "Connector",
    "LocalFilesConnector",
    "LocalRoot",
    "RawDocument",
]
