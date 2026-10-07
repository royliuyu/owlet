"""Local-files connector: discovery, incremental cursor, and safe fetch."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from core.connectors.local_files import LocalFilesConnector, LocalRoot
from core.domain.errors import InvalidSourceIdError, SourceNotFoundError


def _collect(connector: LocalFilesConnector, cursor: str | None):
    async def _run():
        pages = []
        async for page in connector.list_changes(cursor):
            pages.append(page)
        return pages

    return asyncio.run(_run())


def _write(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_discovers_pdf_word_markdown_and_plain_text(tmp_path: Path) -> None:
    _write(tmp_path, "papers/attention.PDF", b"%PDF-1.4")
    _write(tmp_path, "notes/idea.md", b"# idea")
    _write(tmp_path, "notes/draft.markdown", b"draft")
    _write(tmp_path, "notes/todo.txt", b"buy milk")
    _write(tmp_path, "docs/spec.docx", b"PK\x03\x04")
    _write(tmp_path, "ignore.csv", b"a,b")
    _write(tmp_path, "legacy.doc", b"old")
    _write(tmp_path, ".hidden/secret.md", b"hidden")
    _write(tmp_path, "notes/~$draft.md", b"lock")

    connector = LocalFilesConnector.from_directory(tmp_path, root_id="library")
    page = _collect(connector, None)[0]
    found = {change.source_id for change in page.changes}

    assert found == {
        "library/papers/attention.PDF",
        "library/notes/idea.md",
        "library/notes/draft.markdown",
        "library/notes/todo.txt",
        "library/docs/spec.docx",
    }
    assert all(change.op == "upsert" for change in page.changes)


def test_second_scan_is_empty_until_bytes_change(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.pdf", b"v1")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="papers")

    first = _collect(connector, None)[0]
    assert len(first.changes) == 1
    assert first.changes[0].content_hash == hashlib.sha256(b"v1").hexdigest()

    second = _collect(connector, first.cursor)[0]
    assert second.changes == []

    path.write_bytes(b"v2")
    third = _collect(connector, second.cursor)[0]
    assert len(third.changes) == 1
    assert third.changes[0].op == "upsert"
    assert third.changes[0].content_hash == hashlib.sha256(b"v2").hexdigest()


def test_mtime_touch_without_new_bytes_is_not_an_upsert(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.md", b"same")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="notes")
    first = _collect(connector, None)[0]

    later = path.stat().st_mtime + 30
    os.utime(path, (later, later))
    second = _collect(connector, first.cursor)[0]

    before = json.loads(first.cursor)["files"]["notes/a.md"]
    after = json.loads(second.cursor)["files"]["notes/a.md"]
    assert second.changes == []
    assert after["hash"] == hashlib.sha256(b"same").hexdigest() == before["hash"]
    assert after["mtime_ns"] != before["mtime_ns"]


def test_missing_file_is_a_delete(tmp_path: Path) -> None:
    path = _write(tmp_path, "gone.docx", b"doc")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="docs")
    first = _collect(connector, None)[0]
    path.unlink()

    second = _collect(connector, first.cursor)[0]
    assert [(change.op, change.source_id) for change in second.changes] == [
        ("delete", "docs/gone.docx")
    ]


def test_fetch_returns_bytes_and_kind(tmp_path: Path) -> None:
    _write(tmp_path, "deep/paper.pdf", b"%PDF body")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="lib", collection="ml")

    raw = asyncio.run(connector.fetch("lib/deep/paper.pdf"))

    assert raw.source == "paper"
    assert raw.content == b"%PDF body"
    assert raw.content_hash == hashlib.sha256(b"%PDF body").hexdigest()
    assert raw.media_type == "application/pdf"
    assert raw.collection == "ml"
    assert raw.title == "paper"
    assert raw.extra["format"] == "pdf"
    assert raw.uri.startswith("file:")

    doc = connector.to_document(raw)
    assert doc.id == "paper:lib/deep/paper.pdf"
    assert connector.resolve_uri(doc) == raw.uri


def test_fetch_rejects_paths_outside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_bytes(b"secret")
    connector = LocalFilesConnector.from_directory(root, root_id="root")

    with pytest.raises(InvalidSourceIdError):
        asyncio.run(connector.fetch("root/../secret.md"))
    with pytest.raises(InvalidSourceIdError):
        asyncio.run(connector.fetch("other/secret.md"))
    with pytest.raises(SourceNotFoundError):
        asyncio.run(connector.fetch("root/missing.md"))


def test_two_roots_do_not_share_ids(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a, "note.md", b"from-a")
    _write(b, "note.md", b"from-b")
    connector = LocalFilesConnector(
        [LocalRoot(a, id="alpha"), LocalRoot(b, id="beta", collection="beta-notes")]
    )

    page = _collect(connector, None)[0]
    by_id = {change.source_id: change.content_hash for change in page.changes}
    assert set(by_id) == {"alpha/note.md", "beta/note.md"}
    assert by_id["alpha/note.md"] != by_id["beta/note.md"]

    raw = asyncio.run(connector.fetch("beta/note.md"))
    assert raw.source == "note"
    assert raw.content == b"from-b"
    assert raw.collection == "beta-notes"


def test_missing_root_does_not_wipe_the_index(tmp_path: Path) -> None:
    connector = LocalFilesConnector.from_directory(tmp_path / "absent", root_id="papers")
    with pytest.raises(SourceNotFoundError):
        _collect(connector, None)


def test_plain_text_is_a_note(tmp_path: Path) -> None:
    _write(tmp_path, "notes/todo.txt", b"buy milk")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="lib")

    raw = asyncio.run(connector.fetch("lib/notes/todo.txt"))

    assert raw.source == "note"
    assert raw.media_type == "text/plain"
    assert raw.extra["format"] == "plain"
    assert raw.content == b"buy milk"


def test_list_documents_labels_pdf_as_paper(tmp_path: Path) -> None:
    _write(tmp_path, "deep/attention.pdf", b"%PDF-1.4")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="lib", collection="ml")

    documents = asyncio.run(connector.list_documents())

    assert len(documents) == 1
    document = documents[0]
    assert document.id == "paper:lib/deep/attention.pdf"
    assert document.source == "paper"
    assert document.title == "attention"
    assert document.collection == "ml"
    assert document.extra["format"] == "pdf"
    assert document.content_hash == hashlib.sha256(b"%PDF-1.4").hexdigest()


def test_rejects_a_corrupt_cursor(tmp_path: Path) -> None:
    _write(tmp_path, "a.pdf", b"x")
    connector = LocalFilesConnector.from_directory(tmp_path, root_id="papers")
    with pytest.raises(ValueError):
        _collect(connector, "{")
