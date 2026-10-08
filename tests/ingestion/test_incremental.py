"""Index new and changed files follows the content hash, not the chunk layout."""

import asyncio
from pathlib import Path

from core.config import ChunkSettings
from core.connectors.local_files import LocalFilesConnector
from core.ingestion.pipeline import Indexer, IndexProgress
from core.store import DocumentStore, SqliteVecStore


class _Embedder:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def test_a_new_chunk_layout_does_not_rebuild_unchanged_files(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("The same note.", encoding="utf-8")
    (tmp_path / "two.md").write_text("Another note.", encoding="utf-8")
    embedder = _Embedder()

    first = asyncio.run(_run(tmp_path, ChunkSettings(), embedder))
    second = asyncio.run(_run(tmp_path, ChunkSettings(target_tokens=600), embedder))

    assert first.documents_indexed == 2
    assert second.documents_indexed == 0
    assert second.documents_skipped == 2
    assert second.chunks_written == 0
    assert embedder.calls == 1


def test_only_the_edited_file_is_reindexed(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("Original.", encoding="utf-8")
    (tmp_path / "two.md").write_text("Stays.", encoding="utf-8")
    embedder = _Embedder()
    settings = ChunkSettings()

    asyncio.run(_run(tmp_path, settings, embedder))
    (tmp_path / "one.md").write_text("Edited.", encoding="utf-8")
    second = asyncio.run(_run(tmp_path, settings, embedder))

    assert second.documents_indexed == 1
    assert second.documents_skipped == 1
    assert second.chunks_written > 0


async def _run(folder: Path, chunking: ChunkSettings, embedder: _Embedder) -> IndexProgress:
    db = folder / "meta.db"
    indexer = Indexer(
        documents=DocumentStore(db, embedding_dim=4),
        vectors=SqliteVecStore(db, model="test", dim=4),
        embedder=embedder,
        chunking=chunking,
    )
    return await indexer.run(LocalFilesConnector.from_directory(folder, root_id="notes"))
