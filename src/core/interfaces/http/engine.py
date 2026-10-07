"""One assembled stack: stores, models, retrieval, indexing.

Built once per app so the SQLite paths, the embedding model and the
vector dimension are decided in a single place. Everything downstream
takes what it needs from here rather than reaching for settings.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from core.config import Settings
from core.connectors.google import GoogleConnector
from core.connectors.local_files import LocalFilesConnector, LocalRoot
from core.domain.models import Citation
from core.ingestion.pipeline import Indexer, IndexProgress
from core.llm import OllamaClient
from core.retrieval import Retriever
from core.retrieval.answer import citations_for, stream_answer
from core.retrieval.hybrid import Retrieved
from core.store import DocumentStore, IndexedDocument, SourceStore, SqliteVecStore
from core.store.google_accounts import GoogleAccountStore
from core.store.tokens import KeyringTokenStore


class Engine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sources = SourceStore(settings.db_path)
        self.accounts = GoogleAccountStore(settings.db_path)
        self.tokens = KeyringTokenStore()
        self.google = GoogleConnector(settings, self.accounts, self.tokens)
        self.documents = DocumentStore(
            settings.db_path, embedding_dim=settings.llm.embedding_dim
        )
        self.vectors = SqliteVecStore(
            settings.db_path,
            model=settings.llm.embedding_model,
            dim=settings.llm.embedding_dim,
        )
        self.llm = OllamaClient(
            base_url=settings.llm.base_url,
            model=settings.llm.model,
            embedding_model=settings.llm.embedding_model,
            embedding_dim=settings.llm.embedding_dim,
            timeout=settings.llm.timeout,
            num_ctx=settings.llm.num_ctx,
            embed_batch=settings.llm.embed_batch,
        )
        self.retriever = Retriever(
            documents=self.documents,
            vectors=self.vectors,
            embedder=self.llm,
            settings=settings.retrieval,
        )
        self.indexer = Indexer(
            documents=self.documents,
            vectors=self.vectors,
            embedder=self.llm,
            chunking=settings.chunking,
        )
        self._progress: IndexProgress | None = None
        self._task: asyncio.Task[IndexProgress] | None = None

    def connector(self) -> LocalFilesConnector | None:
        records = self.sources.list(enabled_only=True)
        if not records:
            return None
        return LocalFilesConnector(
            LocalRoot(path=item.path, id=item.id, collection=item.collection)
            for item in records
        )

    @property
    def indexing(self) -> bool:
        return self._task is not None and not self._task.done()

    def index_status(self) -> dict[str, object]:
        base: dict[str, object] = {"running": self.indexing}
        base.update(self.documents.stats())
        if self._progress is not None:
            base.update(self._progress.snapshot())
        elif not self.indexing:
            base["status"] = "idle"
        return base

    def start_index(self, *, force: bool = False) -> dict[str, object]:
        """Kick off a run in the background. One at a time."""
        if self.indexing:
            return self.index_status()
        connector = self.connector()
        if connector is None:
            return {
                "running": False,
                "status": "idle",
                "detail": "No folders are configured yet.",
                **self.documents.stats(),
            }

        def remember(progress: IndexProgress) -> None:
            self._progress = progress

        self._task = asyncio.create_task(
            self.indexer.run(connector, on_progress=remember, force=force)
        )
        return self.index_status()

    def citations_for(
        self, hits: Sequence[Retrieved], documents: dict[str, IndexedDocument]
    ) -> list[Citation]:
        return citations_for(hits, documents)

    def stream_answer(
        self,
        question: str,
        hits: Sequence[Retrieved],
        documents: dict[str, IndexedDocument],
        *,
        prior_question: str | None = None,
    ) -> AsyncIterator[str]:
        return stream_answer(
            self.llm, question, hits, documents, prior_question=prior_question
        )
