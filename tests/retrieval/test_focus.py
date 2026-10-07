"""Which paper a follow-up is about, before any search runs."""

from core.retrieval.focus import decide, metadata_answer
from core.store import IndexedDocument


def _paper(
    doc_id: str,
    title: str,
    *,
    filename: str = "",
    authors: tuple[str, ...] = (),
    year: int | None = None,
    venue: str = "",
    doi: str = "",
) -> IndexedDocument:
    return IndexedDocument(
        id=doc_id,
        title=title,
        uri=f"file:///{doc_id}",
        source="paper",
        collection="papers",
        content_hash="hash",
        chunking_version="v",
        indexed_at=None,
        filename=filename or title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
    )


AROD = _paper(
    "paper:arod",
    "AROD: Adaptive Resource-aware Object Detection",
    filename="AROD_Adaptive_Resource",
    authors=("Yu Liu", "Kyoung-Don Kang"),
    year=2024,
    venue="2024 IEEE Vehicular Technology Conference",
    doi="10.1109/vtc.2024",
)
CORUN = _paper(
    "paper:corun",
    "Corun: Concurrent Inference and Continuous Training",
    filename="Corun_Concurrent_Inference",
    authors=("Yu Liu", "Anurag Andhare", "Kyoung-Don Kang"),
    year=2024,
)
HADD = _paper("paper:hadd", "HADD: High-Accuracy Drift Detection", filename="HADD_High_Accuracy")
LIBRARY = (AROD, CORUN, HADD)


def test_this_paper_keeps_the_focused_document() -> None:
    decision = decide("What's this paper's author?", focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.kind == "metadata"
    assert decision.field == "authors"
    assert decision.doc_ids == (AROD.id,)


def test_a_content_follow_up_stays_on_the_focused_paper() -> None:
    decision = decide("How does the scheduler work?", focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.kind == "content"
    assert decision.doc_ids == (AROD.id,)


def test_naming_another_paper_leaves_the_focus() -> None:
    decision = decide("How does Corun schedule jobs?", focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.kind == "content"
    assert decision.doc_ids == (CORUN.id,)


def test_compare_without_two_names_searches_the_library() -> None:
    decision = decide(
        "Compare this paper with other approaches", focus_doc_id=AROD.id, papers=LIBRARY
    )

    assert decision.kind == "library"
    assert decision.doc_ids == ()


def test_compare_names_both_papers() -> None:
    decision = decide("Compare AROD and Corun", focus_doc_id=None, papers=LIBRARY)

    assert decision.kind == "content"
    assert set(decision.doc_ids) == {AROD.id, CORUN.id}


def test_an_author_question_without_focus_searches_the_library() -> None:
    decision = decide("What's the author?", focus_doc_id=None, papers=LIBRARY)

    assert decision.kind == "library"


def test_who_wrote_a_named_paper_reads_its_record() -> None:
    decision = decide("Who wrote Corun?", focus_doc_id=None, papers=LIBRARY)

    assert decision.kind == "metadata"
    assert decision.field == "authors"
    assert decision.doc_ids == (CORUN.id,)


def test_an_unknown_focus_is_ignored() -> None:
    decision = decide("How does the scheduler work?", focus_doc_id="paper:missing", papers=LIBRARY)

    assert decision.kind == "library"


def test_a_long_mention_of_author_is_not_a_metadata_question() -> None:
    asked = (
        "The author claims the throughput doubles because the scheduler "
        "batches jobs and overlaps communication with the next step of training"
    )
    decision = decide(asked, focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.kind == "content"
    assert decision.field is None


def test_the_second_author_stays_on_the_focused_paper() -> None:
    hadd = _paper(
        "paper:hadd-full",
        "HADD: High-Accuracy Detection of Depressed Mood",
        filename="HADD_High-Accuracy",
        authors=("Yu Liu", "Kyoung-Don Kang", "Mi Jin Doe"),
    )
    library = (AROD, CORUN, hadd)
    decision = decide(
        "who is the second author of this paper", focus_doc_id=hadd.id, papers=library
    )

    assert decision.kind == "metadata"
    assert decision.field == "authors"
    assert decision.author_index == 2
    assert decision.doc_ids == (hadd.id,)
    assert metadata_answer(hadd, "authors", index=decision.author_index) == (
        "The second author of HADD: High-Accuracy Detection of Depressed Mood "
        "is Kyoung-Don Kang."
    )


def test_naming_a_paper_picks_that_papers_second_author() -> None:
    decision = decide("who is the second author of AROD", focus_doc_id=HADD.id, papers=LIBRARY)

    assert decision.doc_ids == (AROD.id,)
    assert decision.author_index == 2
    assert metadata_answer(AROD, "authors", index=2) == (
        "The second author of AROD: Adaptive Resource-aware Object Detection is Kyoung-Don Kang."
    )


def test_an_ordinal_past_the_end_of_the_list_says_so() -> None:
    sentence = metadata_answer(AROD, "authors", index=8)

    assert sentence == (
        "AROD: Adaptive Resource-aware Object Detection lists 2 authors, "
        "so there is no eighth author."
    )


def test_a_library_list_by_person_ignores_the_focused_paper() -> None:
    asked = "you search the library, and list all the paper title written by Yu Liu"
    decision = decide(asked, focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.kind == "records"
    assert decision.people == ("Yu Liu",)
    assert decision.doc_ids == ()


def test_a_person_mentioned_in_a_content_question_stays_on_the_paper() -> None:
    decision = decide(
        "How does Yu Liu improve the scheduler?", focus_doc_id=AROD.id, papers=LIBRARY
    )

    assert decision.kind == "content"
    assert decision.doc_ids == (AROD.id,)


TORO_MANUAL = _paper(
    "paper:macbot/retrofit_mower/toro4000/toro4000_operation_manual.pdf",
    "toro4000_operation_manual",
)
TORO_SCHEMATIC = _paper(
    "paper:macbot/retrofit_mower/toro4000/toro4000pro_schematic_diagram.pdf",
    "toro4000pro_schematic_diagram",
)
ZTR = _paper(
    "note:macbot/Mower-Nav-main/src/ztr_webots_sim/sysid/ZTR_HIL_MODEL.md",
    "ZTR_HIL_MODEL",
)
TORO_YARD = (TORO_MANUAL, TORO_SCHEMATIC, ZTR, AROD)


def test_similar_prompts_about_a_model_code_share_one_family() -> None:
    spring = decide(
        "what's the model of neutral spring for toro4000",
        focus_doc_id=ZTR.id,
        papers=TORO_YARD,
    )
    diagram = decide(
        "find the schematic electrical diagram of tor04000",
        focus_doc_id=None,
        papers=TORO_YARD,
    )

    assert spring.kind == "content"
    assert spring.doc_ids == diagram.doc_ids
    assert spring.doc_ids == (TORO_MANUAL.id, TORO_SCHEMATIC.id)


def test_a_named_page_stays_on_that_page_of_the_named_file() -> None:
    catalogue = _paper(
        "paper:macbot/retrofit_mower/toro4000/toro4000_ridding_mower_part_catalogue.pdf",
        "60in Z Master 4000 Series",
        filename="toro4000_ridding_mower_part_catalogue.pdf",
    )
    decision = decide(
        "check 60in Z Master 4000 Series again and look for it on the page 27",
        focus_doc_id=ZTR.id,
        papers=(catalogue, TORO_MANUAL, TORO_SCHEMATIC, ZTR),
    )

    assert decision.kind == "content"
    assert decision.page == 27
    assert decision.doc_ids == (catalogue.id,)


def test_a_page_follow_up_stays_on_the_focused_document() -> None:
    decision = decide("look for it on page 27", focus_doc_id=AROD.id, papers=LIBRARY)

    assert decision.page == 27
    assert decision.doc_ids == (AROD.id,)


def test_a_split_model_code_joins_the_same_family() -> None:
    decision = decide("neutral spring for toro 4000", focus_doc_id=ZTR.id, papers=TORO_YARD)

    assert decision.doc_ids == (TORO_MANUAL.id, TORO_SCHEMATIC.id)


def test_metadata_answer_uses_the_record_and_refuses_an_empty_field() -> None:
    assert metadata_answer(AROD, "authors") == (
        "AROD: Adaptive Resource-aware Object Detection is by Yu Liu, Kyoung-Don Kang."
    )
    assert metadata_answer(HADD, "authors") is None
    assert metadata_answer(AROD, "year") == (
        "AROD: Adaptive Resource-aware Object Detection was published in 2024."
    )
    assert metadata_answer(AROD, "doi") == (
        "The DOI of AROD: Adaptive Resource-aware Object Detection is 10.1109/vtc.2024."
    )
