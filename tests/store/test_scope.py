"""Search stays inside the papers a question named."""

from datetime import datetime, timezone
from pathlib import Path

from core.domain.models import Chunk, Document
from core.store import DocumentStore
from core.store.vectors import SqliteVecStore


def test_fulltext_can_be_limited_to_one_document(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "meta.db")
    _index(store, "paper:arod", "the scheduler assigns jobs on the device")
    _index(store, "paper:hadd", "the scheduler assigns jobs in the cloud")

    hits = store.search_fulltext("scheduler", limit=10, doc_ids=["paper:arod"])

    assert [hit.chunk.doc_id for hit in hits] == ["paper:arod"]


def test_a_named_page_does_not_return_the_pages_around_it(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "meta.db")
    _index(
        store,
        "paper:catalogue",
        "",
        pages=[(0, 26, "Caster and Wheel Assembly"), (1, 27, "Spring-Return, Neutral 126-8195")],
    )

    hits = store.chunks_on_page("paper:catalogue", 27)

    assert [hit.text for hit in hits] == ["Spring-Return, Neutral 126-8195"]


def test_a_part_name_is_found_when_the_rank_list_missed_it(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path / "meta.db")
    _index(store, "paper:manual", "RETURN TO NEUTRAL ASSEMBLY OPTION")
    _index(store, "paper:catalogue", "11 126-8195 1 Spring-Return, Neutral", page=27)

    hits = store.chunks_containing(
        ("Spring-Return",), doc_ids=["paper:manual", "paper:catalogue"], page=27
    )

    assert [hit.doc_id for hit in hits] == ["paper:catalogue"]


def test_search_among_ranks_only_the_given_chunks(tmp_path: Path) -> None:
    path = tmp_path / "meta.db"
    documents = DocumentStore(path, embedding_dim=2)
    _index(documents, "paper:near", "the close passage")
    _index(documents, "paper:far", "the distant passage")
    store = SqliteVecStore(path, model="test", dim=2)
    store.upsert(["paper:near:0", "paper:far:0"], [[1.0, 0.0], [0.0, 1.0]])

    hits = store.search_among([0.2, 0.9], ["paper:near:0"], limit=5)

    assert [hit.chunk_id for hit in hits] == ["paper:near:0"]
    assert store.search_among([1.0, 0.0], [], limit=5) == []


def _index(
    store: DocumentStore,
    doc_id: str,
    text: str,
    *,
    page: int = 1,
    ord: int = 0,
    pages: list[tuple[int, int, str]] | None = None,
) -> None:
    now = datetime.now(tz=timezone.utc)
    source, source_id = doc_id.split(":", 1)
    store.upsert_document(
        Document(
            id=doc_id,
            source=source,  # type: ignore[arg-type]
            source_id=source_id,
            title=source_id,
            uri=f"file:///{source_id}",
            created_at=now,
            updated_at=now,
            content_hash=doc_id,
        ),
        root_id="root",
        page_count=1,
        parser="pdf",
    )
    rows = pages if pages is not None else [(ord, page, text)]
    store.replace_chunks(
        doc_id,
        [
            Chunk(
                id=f"{doc_id}:{order}",
                doc_id=doc_id,
                ord=order,
                text=body,
                token_count=4,
                page_start=page_no,
                page_end=page_no,
            )
            for order, page_no, body in rows
        ],
        chunking_version="test",
    )
