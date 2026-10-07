"""The folder list in SQLite."""

from pathlib import Path

import pytest

from core.domain.errors import (
    DuplicateSourceError,
    InvalidSourceIdError,
    SourceNotFoundError,
)
from core.store import SourceStore


def _store(tmp_path: Path) -> SourceStore:
    return SourceStore(tmp_path / "state" / "metadata.db")


def test_add_derives_an_id_and_label_from_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "My Papers"
    folder.mkdir()
    store = _store(tmp_path)

    record = store.add(folder)

    assert record.id == "my-papers"
    assert record.collection == "My Papers"
    assert record.enabled is True
    assert record.path == folder.resolve()
    assert [item.id for item in store.list()] == ["my-papers"]


def test_two_folders_with_the_same_name_get_distinct_ids(tmp_path: Path) -> None:
    first = tmp_path / "a" / "notes"
    second = tmp_path / "b" / "notes"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    store = _store(tmp_path)

    assert store.add(first).id == "notes"
    assert store.add(second).id == "notes-2"


def test_overlapping_folders_are_rejected(tmp_path: Path) -> None:
    outer = tmp_path / "papers"
    inner = outer / "2024"
    inner.mkdir(parents=True)
    store = _store(tmp_path)
    store.add(outer)

    with pytest.raises(DuplicateSourceError):
        store.add(outer)
    with pytest.raises(DuplicateSourceError):
        store.add(inner)


def test_a_path_that_is_not_a_folder_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    file_path = tmp_path / "notes.md"
    file_path.write_text("hello", encoding="utf-8")

    with pytest.raises(SourceNotFoundError):
        store.add(tmp_path / "nowhere")
    with pytest.raises(SourceNotFoundError):
        store.add(file_path)


def test_an_explicit_id_must_be_usable_as_a_prefix(tmp_path: Path) -> None:
    folder = tmp_path / "papers"
    folder.mkdir()
    store = _store(tmp_path)

    with pytest.raises(InvalidSourceIdError):
        store.add(folder, source_id="pap/ers")


def test_update_renames_and_disables(tmp_path: Path) -> None:
    folder = tmp_path / "papers"
    folder.mkdir()
    store = _store(tmp_path)
    store.add(folder)

    renamed = store.update("papers", label="Reading list")
    assert renamed.collection == "Reading list"
    assert renamed.enabled is True

    disabled = store.update("papers", enabled=False)
    assert disabled.enabled is False
    assert disabled.collection == "Reading list"
    assert store.list(enabled_only=True) == []
    assert len(store.list()) == 1

    with pytest.raises(SourceNotFoundError):
        store.update("missing", label="x")


def test_remove_reports_whether_anything_was_deleted(tmp_path: Path) -> None:
    folder = tmp_path / "papers"
    folder.mkdir()
    store = _store(tmp_path)
    store.add(folder)

    assert store.remove("papers") is True
    assert store.remove("papers") is False
    assert store.list() == []


def test_the_list_survives_a_new_store_on_the_same_file(tmp_path: Path) -> None:
    folder = tmp_path / "papers"
    folder.mkdir()
    db = tmp_path / "state" / "metadata.db"
    SourceStore(db).add(folder, label="Papers")

    assert [item.collection for item in SourceStore(db).list()] == ["Papers"]
