"""Local PDF, Word, Markdown, and plain-text connector.

The walk comes from Knowledge-Base-Intelligent-Paper-Retrieval
`get_vectorstore`, which recursively collected every `.pdf` under a
user-selected folder. This adapter keeps that walk, adds `.docx`,
Markdown, and `.txt`, and stops at raw bytes plus a content hash.

Incremental sync uses mtime and size as the cheap check, then sha256
when either changes. Unchanged files are not re-read. Text extraction
and chunking belong in `ingestion/parse`, not here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from core.connectors.base import Change, ChangeSet, RawDocument
from core.domain.errors import InvalidSourceIdError, SourceNotFoundError
from core.domain.models import Document, SourceKind

# suffix -> (document kind, media type, format key for the parser)
_FORMATS: dict[str, tuple[SourceKind, str, str]] = {
    ".pdf": ("paper", "application/pdf", "pdf"),
    ".docx": (
        "file",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    ".md": ("note", "text/markdown", "markdown"),
    ".markdown": ("note", "text/markdown", "markdown"),
    ".txt": ("note", "text/plain", "plain"),
}

SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_FORMATS)

_CURSOR_VERSION = 1
_SKIP_DIRS = frozenset({"__pycache__", "node_modules"})


class _Snapshot(NamedTuple):
    mtime_ns: int
    size: int
    hash: str


@dataclass(frozen=True, slots=True)
class LocalRoot:
    """One configured directory. `id` becomes the source-id prefix."""

    path: Path
    id: str | None = None
    collection: str | None = None


class LocalFilesConnector:
    """Scan configured directories for PDF, Word, Markdown, and plain text.

    `source` is the sync_state key for this adapter. Each document's own
    `source` is finer: PDF → paper, Markdown and plain text → note, Word → file.
    """

    source: SourceKind = "file"

    def __init__(self, roots: Iterable[LocalRoot]) -> None:
        normalized: list[tuple[LocalRoot, str]] = []
        seen: set[str] = set()
        for root in roots:
            root_id = root.id or Path(root.path).name
            if not root_id or "/" in root_id or "\\" in root_id:
                raise ValueError(f"Invalid root id: {root_id!r}")
            if root_id in seen:
                raise ValueError(f"Duplicate root id: {root_id}")
            seen.add(root_id)
            collection = root.collection if root.collection is not None else root_id
            normalized.append((LocalRoot(Path(root.path), root_id, collection), root_id))
        if not normalized:
            raise ValueError("LocalFilesConnector requires at least one root")
        self._roots = normalized

    @classmethod
    def from_directory(
        cls,
        path: Path | str,
        *,
        root_id: str | None = None,
        collection: str | None = None,
    ) -> LocalFilesConnector:
        """Single-folder adapter, matching the old pdf_directory argument."""
        return cls([LocalRoot(path=Path(path), id=root_id, collection=collection)])

    async def list_changes(self, cursor: str | None) -> AsyncIterator[ChangeSet]:
        changeset = await asyncio.to_thread(self._scan, cursor)
        yield changeset

    async def fetch(self, source_id: str) -> RawDocument:
        return await asyncio.to_thread(self._read, source_id)

    async def list_documents(self) -> list[Document]:
        """Current files under every root, without reading their bytes."""
        return await asyncio.to_thread(self._list_documents)

    def resolve_uri(self, doc: Document) -> str:
        if doc.uri:
            return doc.uri
        return self._locate(doc.source_id)[1].as_uri()

    def to_document(self, raw: RawDocument) -> Document:
        return Document(
            id=f"{raw.source}:{raw.source_id}",
            source=raw.source,
            source_id=raw.source_id,
            title=raw.title,
            uri=raw.uri,
            collection=raw.collection,
            created_at=raw.created_at,
            updated_at=raw.updated_at,
            content_hash=raw.content_hash,
            extra=dict(raw.extra),
        )

    def _scan(self, cursor: str | None) -> ChangeSet:
        previous = _decode_cursor(cursor)
        current: dict[str, _Snapshot] = {}
        changes: list[Change] = []

        for root, root_id in self._roots:
            root_path = Path(root.path).resolve()
            if not root_path.is_dir():
                raise SourceNotFoundError(
                    f"Local root {root_id!r} is not a directory: {root_path}"
                )
            for source_id, file_path in _walk_supported(root_path, root_id):
                try:
                    stat = file_path.stat()
                except OSError:
                    prior = previous.get(source_id)
                    if prior is not None:
                        current[source_id] = prior
                    continue
                prior = previous.get(source_id)
                if (
                    prior is not None
                    and prior.mtime_ns == stat.st_mtime_ns
                    and prior.size == stat.st_size
                ):
                    current[source_id] = prior
                    continue
                try:
                    digest = _hash_file(file_path)
                except OSError:
                    if prior is not None:
                        current[source_id] = prior
                    continue
                current[source_id] = _Snapshot(stat.st_mtime_ns, stat.st_size, digest)
                if prior is None or prior.hash != digest:
                    changes.append(
                        Change(
                            op="upsert",
                            source_id=source_id,
                            content_hash=digest,
                            updated_at=_from_timestamp(stat.st_mtime),
                        )
                    )

        for source_id in previous:
            if source_id not in current:
                changes.append(Change(op="delete", source_id=source_id))

        changes.sort(key=lambda change: (change.source_id, change.op))
        return ChangeSet(changes=changes, cursor=_encode_cursor(current))

    def _list_documents(self) -> list[Document]:
        snapshots = _decode_cursor(self._scan(None).cursor)
        documents: list[Document] = []
        for source_id, snap in snapshots.items():
            try:
                root, path = self._locate(source_id)
                stat = path.stat()
            except (InvalidSourceIdError, SourceNotFoundError, OSError):
                continue
            kind, media_type, fmt = _FORMATS[path.suffix.lower()]
            rel = source_id.split("/", 1)[1]
            documents.append(
                Document(
                    id=f"{kind}:{source_id}",
                    source=kind,
                    source_id=source_id,
                    title=path.stem,
                    uri=path.as_uri(),
                    collection=root.collection,
                    created_at=_created_at(stat),
                    updated_at=_from_timestamp(stat.st_mtime),
                    content_hash=snap.hash,
                    extra={
                        "format": fmt,
                        "media_type": media_type,
                        "relative_path": rel,
                        "root_id": root.id,
                    },
                )
            )
        documents.sort(key=lambda doc: (doc.collection or "", doc.title.lower(), doc.id))
        return documents

    def _read(self, source_id: str) -> RawDocument:
        root, path = self._locate(source_id)
        try:
            content = path.read_bytes()
            stat = path.stat()
        except OSError as exc:
            raise SourceNotFoundError(source_id) from exc
        kind, media_type, fmt = _FORMATS[path.suffix.lower()]
        rel = source_id.split("/", 1)[1]
        updated_at = _from_timestamp(stat.st_mtime)
        created_at = _created_at(stat)
        return RawDocument(
            source_id=source_id,
            source=kind,
            title=path.stem,
            uri=path.as_uri(),
            media_type=media_type,
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            created_at=created_at,
            updated_at=updated_at,
            collection=root.collection,
            extra={
                "format": fmt,
                "media_type": media_type,
                "relative_path": rel,
                "root_id": root.id,
            },
        )

    def _locate(self, source_id: str) -> tuple[LocalRoot, Path]:
        root_id, sep, rel = source_id.partition("/")
        if not sep or not rel or "\\" in source_id:
            raise InvalidSourceIdError(source_id)
        root = next((item for item, rid in self._roots if rid == root_id), None)
        if root is None:
            raise InvalidSourceIdError(source_id)
        relative = PurePosixPath(rel)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise InvalidSourceIdError(source_id)
        suffix = relative.suffix.lower()
        if suffix not in _FORMATS:
            raise InvalidSourceIdError(source_id)
        root_path = Path(root.path).resolve()
        candidate = (root_path.joinpath(*relative.parts)).resolve()
        if not candidate.is_relative_to(root_path):
            raise InvalidSourceIdError(source_id)
        if not candidate.is_file():
            raise SourceNotFoundError(source_id)
        return root, candidate


def _walk_supported(root_path: Path, root_id: str) -> Iterable[tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in _SKIP_DIRS
        ]
        for name in filenames:
            if name.startswith(".") or name.startswith("~$"):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in _FORMATS:
                continue
            file_path = Path(dirpath) / name
            if file_path.is_symlink():
                try:
                    resolved = file_path.resolve()
                except OSError:
                    continue
                if not resolved.is_file() or not resolved.is_relative_to(root_path):
                    continue
                file_path = resolved
            rel = (Path(dirpath) / name).relative_to(root_path).as_posix()
            yield f"{root_id}/{rel}", file_path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _created_at(stat: os.stat_result) -> datetime:
    # Windows st_ctime is creation time. Elsewhere prefer birth time when present.
    birth = getattr(stat, "st_birthtime", None)
    timestamp = birth if isinstance(birth, (int, float)) else stat.st_ctime
    return _from_timestamp(timestamp)


def _decode_cursor(cursor: str | None) -> dict[str, _Snapshot]:
    if cursor is None:
        return {}
    try:
        payload = json.loads(cursor)
    except json.JSONDecodeError as exc:
        raise ValueError("Local-files cursor is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValueError("Unsupported local-files cursor version")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("Local-files cursor is missing files")
    snapshot: dict[str, _Snapshot] = {}
    for source_id, raw in files.items():
        if not isinstance(source_id, str) or not isinstance(raw, Mapping):
            raise ValueError("Local-files cursor has a malformed file entry")
        try:
            snapshot[source_id] = _Snapshot(
                mtime_ns=int(raw["mtime_ns"]),
                size=int(raw["size"]),
                hash=str(raw["hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Local-files cursor has a malformed file entry") from exc
    return snapshot


def _encode_cursor(files: Mapping[str, _Snapshot]) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "files": {
            source_id: {
                "mtime_ns": item.mtime_ns,
                "size": item.size,
                "hash": item.hash,
            }
            for source_id, item in sorted(files.items())
        },
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
