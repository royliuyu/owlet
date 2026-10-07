"""Which documents a person is filed under, read from the records."""

from tests.retrieval.test_focus import AROD, CORUN, HADD, LIBRARY

from core.retrieval.records import people_asked, records_answer, select_records
from core.store import IndexedDocument


def test_every_document_filed_under_the_person_is_returned() -> None:
    third = _paper(
        "paper:frames",
        "Filtering empty video frames",
        authors=("Yu Liu",),
        year=2024,
    )
    library = (*LIBRARY, third)

    found = select_records(library, ("Yu Liu",))

    assert [document.id for document in found] == [AROD.id, CORUN.id, "paper:frames"]
    assert HADD.id not in {document.id for document in found}


def test_a_shared_last_name_still_matches_the_stored_person() -> None:
    found = select_records(LIBRARY, ("Kang",))

    assert {document.id for document in found} == {AROD.id, CORUN.id}


def test_a_title_that_is_not_a_stored_person_is_left_alone() -> None:
    assert people_asked("papers by AROD", LIBRARY) is None


def test_an_unknown_person_is_still_a_record_question() -> None:
    assert people_asked("which papers did Ada Lovelace write", LIBRARY) == ("Ada Lovelace",)
    assert select_records(LIBRARY, ("Ada Lovelace",)) == []
    assert records_answer(("Ada Lovelace",), []) == (
        "No document in the library lists Ada Lovelace."
    )


def test_the_sentence_cites_only_the_matched_documents() -> None:
    matched = select_records(LIBRARY, ("Yu Liu",))

    sentence = records_answer(("Yu Liu",), matched)

    assert sentence == (
        "Yu Liu is listed on 2 documents: "
        "[1] AROD: Adaptive Resource-aware Object Detection (2024), "
        "[2] Corun: Concurrent Inference and Continuous Training (2024)."
    )
    assert "HADD" not in sentence


def test_a_source_filter_drops_other_kinds() -> None:
    note = _paper("note:lab", "Lab notes", authors=("Yu Liu",))

    assert select_records((AROD, note), ("Yu Liu",), sources=["note"]) == [note]


def _paper(
    doc_id: str,
    title: str,
    *,
    authors: tuple[str, ...] = (),
    year: int | None = None,
) -> IndexedDocument:
    return IndexedDocument(
        id=doc_id,
        title=title,
        uri=f"file:///{doc_id}",
        source=doc_id.split(":", 1)[0],
        collection="papers",
        content_hash="hash",
        chunking_version="v",
        indexed_at=None,
        filename=title,
        authors=authors,
        year=year,
    )
