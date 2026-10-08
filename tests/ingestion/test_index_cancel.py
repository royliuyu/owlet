"""Cancel stops the run between files and keeps passages already written."""

import asyncio
from pathlib import Path

from core.config import ChunkSettings
from core.connectors.local_files import LocalFilesConnector
from core.ingestion.pipeline import Indexer, IndexProgress
from core.store import DocumentStore, SqliteVecStore


class _Embedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError(f"embedding should not start after cancel, got {len(texts)}")


def test_cancel_stops_before_the_next_file(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("The first note stays indexed.", encoding="utf-8")
    (tmp_path / "two.md").write_text("The second note is not reached.", encoding="utf-8")
    cancel = asyncio.Event()

    def stop_after_first(progress: IndexProgress) -> None:
        if progress.documents_indexed >= 1:
            cancel.set()

    progress = asyncio.run(_run(tmp_path, cancel, on_progress=stop_after_first))

    assert progress.status == "cancelled"
    assert progress.documents_seen == 2
    assert progress.documents_indexed == 1
    assert progress.chunks_written > 0
    assert "stay in the index" in progress.detail


def test_cancel_stops_a_rebuild_the_same_way(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("Already indexed once.", encoding="utf-8")
    (tmp_path / "two.md").write_text("Rebuilt only if the run continues.", encoding="utf-8")
    cancel = asyncio.Event()

    def stop_after_first(progress: IndexProgress) -> None:
        if progress.documents_indexed >= 1:
            cancel.set()

    progress = asyncio.run(_run(tmp_path, cancel, on_progress=stop_after_first, force=True))

    assert progress.status == "cancelled"
    assert progress.documents_indexed == 1


def test_cancel_before_the_run_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("Unread.", encoding="utf-8")
    cancel = asyncio.Event()
    cancel.set()

    progress = asyncio.run(_run(tmp_path, cancel))

    assert progress.status == "cancelled"
    assert progress.documents_indexed == 0
    assert progress.chunks_written == 0


async def _run(
    folder: Path,
    cancel: asyncio.Event,
    *,
    on_progress=None,
    force: bool = False,
) -> IndexProgress:
    db = folder / "meta.db"
    indexer = Indexer(
        documents=DocumentStore(db, embedding_dim=4),
        vectors=SqliteVecStore(db, model="test", dim=4),
        embedder=_Embedder(),
        chunking=ChunkSettings(),
    )
    return await indexer.run(
        LocalFilesConnector.from_directory(folder, root_id="notes"),
        on_progress=on_progress,
        cancel=cancel,
        force=force,
    )
