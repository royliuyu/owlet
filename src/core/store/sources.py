"""The folders owlet reads, owned by SQLite rather than a config file.

Sources change often and are edited from the UI, including from a phone
over Tailscale where no one can reach a YAML file. They also need to sit
next to `sync_state`, which keys its cursor by source id; keeping the two
in different places would let them drift apart.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.domain.errors import (
    DuplicateSourceError,
    InvalidSourceIdError,
    SourceNotFoundError,
)
from core.store.db import migrate, session

LOCAL_FILES = "local_files"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One folder exposed as a library collection."""

    id: str
    kind: str
    path: Path
    collection: str
    enabled: bool
    created_at: datetime


class SourceStore:
    """CRUD over the `sources` table. Every call is its own transaction."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ready = False

    def list(self, *, enabled_only: bool = False) -> list[SourceRecord]:
        clause = " WHERE enabled = 1" if enabled_only else ""
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM sources{clause} ORDER BY created_at, id"
            ).fetchall()
        return [_record(row) for row in rows]

    def get(self, source_id: str) -> SourceRecord | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return _record(row) if row is not None else None

    def add(
        self,
        path: Path | str,
        *,
        label: str | None = None,
        source_id: str | None = None,
    ) -> SourceRecord:
        folder = _usable_directory(path)
        collection = (label or "").strip() or folder.name or str(folder)
        created_at = datetime.now(tz=timezone.utc)
        with self._session() as connection:
            existing = connection.execute("SELECT id, path FROM sources").fetchall()
            _reject_overlap(folder, existing)
            if source_id is None:
                chosen = _unique(_slug(folder.name), {row["id"] for row in existing})
            else:
                chosen = source_id.strip().lower()
                if not _ID_PATTERN.match(chosen):
                    raise InvalidSourceIdError(
                        f"{source_id!r} must be letters, digits, '-' or '_'"
                    )
                if any(row["id"] == chosen for row in existing):
                    raise DuplicateSourceError(f"A folder named {chosen!r} already exists")
            connection.execute(
                "INSERT INTO sources (id, kind, path, collection, enabled, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (chosen, LOCAL_FILES, str(folder), collection, created_at.isoformat()),
            )
        return SourceRecord(
            id=chosen,
            kind=LOCAL_FILES,
            path=folder,
            collection=collection,
            enabled=True,
            created_at=created_at,
        )

    def update(
        self,
        source_id: str,
        *,
        label: str | None = None,
        enabled: bool | None = None,
    ) -> SourceRecord:
        current = self.get(source_id)
        if current is None:
            raise SourceNotFoundError(source_id)
        collection = (label or "").strip() or current.collection
        is_enabled = current.enabled if enabled is None else enabled
        with self._session() as connection:
            connection.execute(
                "UPDATE sources SET collection = ?, enabled = ? WHERE id = ?",
                (collection, int(is_enabled), source_id),
            )
        return SourceRecord(
            id=current.id,
            kind=current.kind,
            path=current.path,
            collection=collection,
            enabled=is_enabled,
            created_at=current.created_at,
        )

    def remove(self, source_id: str) -> bool:
        with self._session() as connection:
            cursor = connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return cursor.rowcount > 0

    def _session(self) -> AbstractContextManager[sqlite3.Connection]:
        if not self._ready:
            migrate(self._db_path)
            self._ready = True
        return session(self._db_path)


def _usable_directory(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if not str(candidate).strip():
        raise SourceNotFoundError("Enter a folder path")
    try:
        resolved = candidate.resolve()
        is_dir = resolved.is_dir()
    except OSError as exc:
        raise SourceNotFoundError(f"{candidate} cannot be read") from exc
    if not is_dir:
        raise SourceNotFoundError(f"{resolved} is not a folder on this computer")
    return resolved


def _reject_overlap(folder: Path, existing: Sequence[sqlite3.Row]) -> None:
    """One file must not arrive under two source ids."""
    for row in existing:
        other = Path(row["path"])
        if folder == other:
            raise DuplicateSourceError(f"{folder} is already added as {row['id']!r}")
        if folder.is_relative_to(other):
            raise DuplicateSourceError(f"{folder} is already inside {row['id']!r}")
        if other.is_relative_to(folder):
            raise DuplicateSourceError(f"{folder} contains {row['id']!r}")


def _slug(name: str) -> str:
    cleaned = _SLUG_SEPARATORS.sub("-", name.lower()).strip("-")
    return cleaned or "folder"


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    for suffix in range(2, len(taken) + 3):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    raise DuplicateSourceError(base)


def _record(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        id=row["id"],
        kind=row["kind"],
        path=Path(row["path"]),
        collection=row["collection"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
