"""Connections and schema for the metadata database.

WAL is on so the background sync and the API can write without blocking
each other. Connections are opened per operation and closed with it:
SQLite objects are bound to the thread that made them, and FastAPI moves
handlers between threads.

Layout note: `chunks` holds the canonical text and every bit of
provenance. Vectors live apart, in `embeddings` plus whichever index is
installed, so swapping sqlite-vec for Chroma or pgvector later touches
one module and never destroys text.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

# Empty pages stay in the file until it is rewritten. A folder removal is
# worth that rewrite when they are at least half the file and at least 32 MB.
FREE_BYTES_FLOOR = 32 * 1024 * 1024

logger = logging.getLogger("uvicorn.error")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'local_files',
    path        TEXT NOT NULL,
    collection  TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    root_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    uri           TEXT NOT NULL,
    collection    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    page_count    INTEGER NOT NULL DEFAULT 0,
    extra_json    TEXT NOT NULL DEFAULT '{}',
    indexed_at    TEXT,
    parser        TEXT,
    deleted_at    TEXT
);

CREATE INDEX IF NOT EXISTS documents_root ON documents (root_id);
CREATE INDEX IF NOT EXISTS documents_hash ON documents (content_hash);

-- The source of truth for retrieved text. An embedding is only an index
-- into this table; answers and citations always read `text` from here.
CREATE TABLE IF NOT EXISTS chunks (
    id               TEXT PRIMARY KEY,
    doc_id           TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord              INTEGER NOT NULL,
    text             TEXT NOT NULL,
    token_count      INTEGER NOT NULL,
    char_start       INTEGER NOT NULL DEFAULT 0,
    char_end         INTEGER NOT NULL DEFAULT 0,
    page_start       INTEGER NOT NULL,
    page_end         INTEGER NOT NULL,
    section_path     TEXT,
    section_kind     TEXT,
    bboxes_json      TEXT NOT NULL DEFAULT '[]',
    chunking_version TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (doc_id, chunking_version, ord)
);

CREATE INDEX IF NOT EXISTS chunks_doc ON chunks (doc_id, ord);
CREATE INDEX IF NOT EXISTS chunks_version ON chunks (chunking_version);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

-- Which model produced a vector, so changing models is a detectable
-- re-index rather than a silent mix of incompatible spaces.
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (chunk_id, model)
);

CREATE TABLE IF NOT EXISTS sync_state (
    source        TEXT NOT NULL,
    account       TEXT NOT NULL DEFAULT '',
    cursor        TEXT,
    last_sync_at  TEXT,
    status        TEXT NOT NULL DEFAULT 'idle',
    detail        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, account)
);

-- The Google client the Settings page saves. The secret is not in this table.
CREATE TABLE IF NOT EXISTS google_client (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    client_id     TEXT NOT NULL,
    account_email TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL
);

-- Google accounts. Refresh tokens are not stored here; they live in the
-- token store (the OS keyring on this machine, a secret store in the cloud).
CREATE TABLE IF NOT EXISTS google_accounts (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    scopes        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'connected',
    last_sync_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_calendars (
    account_id   TEXT NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    calendar_id  TEXT NOT NULL,
    summary      TEXT NOT NULL,
    is_primary   INTEGER NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (account_id, calendar_id)
);

-- Occurrences expanded by Google for the calendars this account has checked.
-- Sync replaces the window; Today reads it. Search indexing is a later step.
CREATE TABLE IF NOT EXISTS google_events (
    account_id  TEXT NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    summary     TEXT NOT NULL,
    start_at    TEXT NOT NULL,
    end_at      TEXT NOT NULL,
    all_day     INTEGER NOT NULL DEFAULT 0,
    location    TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    recurrence  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, calendar_id, event_id)
);

-- One sign-in attempt. `state` sent to Google is this id. The PKCE verifier
-- stays here and never goes to the browser.
CREATE TABLE IF NOT EXISTS oauth_attempts (
    id           TEXT PRIMARY KEY,
    verifier     TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    product      TEXT NOT NULL,
    account_id   TEXT,
    status       TEXT NOT NULL,
    email        TEXT,
    message      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_runs (
    id                TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT NOT NULL,
    documents_seen    INTEGER NOT NULL DEFAULT 0,
    documents_indexed INTEGER NOT NULL DEFAULT 0,
    chunks_written    INTEGER NOT NULL DEFAULT 0,
    chunking_version  TEXT NOT NULL DEFAULT '',
    embedding_model   TEXT NOT NULL DEFAULT '',
    detail            TEXT NOT NULL DEFAULT ''
);
"""


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the database with sqlite-vec loaded, committing on a clean exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def _ensure_google_event_details(connection: sqlite3.Connection) -> None:
    """Add the description and repeat line to events saved before those columns."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(google_events)")}
    if not columns:
        return
    if "description" not in columns:
        connection.execute(
            "ALTER TABLE google_events ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )
    if "recurrence" not in columns:
        connection.execute(
            "ALTER TABLE google_events ADD COLUMN recurrence TEXT NOT NULL DEFAULT ''"
        )


def _ensure_google_account_email(connection: sqlite3.Connection) -> None:
    """Add the sign-in address to clients created before that column existed."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(google_client)")}
    if columns and "account_email" not in columns:
        connection.execute(
            "ALTER TABLE google_client ADD COLUMN account_email TEXT NOT NULL DEFAULT ''"
        )


def free_space_worth_reclaiming(
    *,
    page_size: int,
    page_count: int,
    freelist: int,
    floor_bytes: int = FREE_BYTES_FLOOR,
) -> bool:
    """True when empty pages are at least half the file and past the floor."""
    if page_size <= 0 or page_count <= 0 or freelist <= 0:
        return False
    if freelist * 2 < page_count:
        return False
    return freelist * page_size >= floor_bytes


def reclaim_free_space(path: Path, *, floor_bytes: int = FREE_BYTES_FLOOR) -> bool:
    """Rewrite the file so empty pages go back to the disk.

    A quiet miss, including a file another connection still holds, leaves the
    rows as they are. The next folder removal tries again.
    """
    connection = sqlite3.connect(path, timeout=15.0, isolation_level=None)
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        page_size, page_count, freelist = _pages(connection)
        if not free_space_worth_reclaiming(
            page_size=page_size,
            page_count=page_count,
            freelist=freelist,
            floor_bytes=floor_bytes,
        ):
            return False
        try:
            connection.execute("VACUUM")
        except sqlite3.OperationalError as exc:
            logger.warning("Index file kept its empty pages: %s", exc)
            return False
        return True
    finally:
        connection.close()


def _pages(connection: sqlite3.Connection) -> tuple[int, int, int]:
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
    return int(page_size), int(page_count), int(freelist)


def migrate(path: Path, *, embedding_dim: int | None = None) -> None:
    with session(path) as connection:
        connection.executescript(SCHEMA)
        _ensure_google_account_email(connection)
        _ensure_google_event_details(connection)
        if embedding_dim is not None:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                "chunk_id TEXT PRIMARY KEY, "
                f"embedding float[{embedding_dim}])"
            )
