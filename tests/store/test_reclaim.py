"""Empty pages return to the disk after a large folder removal."""

from pathlib import Path

from core.store.db import (
    FREE_BYTES_FLOOR,
    free_space_worth_reclaiming,
    migrate,
    reclaim_free_space,
    session,
)


def test_half_of_the_file_and_the_floor_are_both_required() -> None:
    page = 4096
    full = FREE_BYTES_FLOOR // page

    assert free_space_worth_reclaiming(page_size=page, page_count=full * 2, freelist=full)
    assert not free_space_worth_reclaiming(page_size=page, page_count=full * 2, freelist=full - 1)
    assert not free_space_worth_reclaiming(page_size=page, page_count=full * 2 + 1, freelist=full)
    assert not free_space_worth_reclaiming(page_size=page, page_count=full * 2, freelist=0)


def test_a_small_hole_stays_in_the_file(tmp_path: Path) -> None:
    path = _hole(tmp_path)
    size = path.stat().st_size

    assert reclaim_free_space(path) is False
    assert path.stat().st_size == size


def test_a_large_hole_is_given_back(tmp_path: Path) -> None:
    path = _hole(tmp_path)
    before = path.stat().st_size

    assert reclaim_free_space(path, floor_bytes=1000) is True

    assert path.stat().st_size < before
    with session(path) as connection:
        freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
        connection.execute("SELECT chunk_id FROM vec_chunks LIMIT 1").fetchall()
    assert freelist == 0


def _hole(tmp_path: Path) -> Path:
    path = tmp_path / "metadata.db"
    migrate(path, embedding_dim=4)
    with session(path) as connection:
        connection.execute("CREATE TABLE ballast (blob BLOB)")
        connection.execute("INSERT INTO ballast (blob) VALUES (?)", (b"x" * 200_000,))
    with session(path) as connection:
        connection.execute("DELETE FROM ballast")
    return path
