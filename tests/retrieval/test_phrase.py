"""Page 27 of the wrong file must not hide the parts row."""

from core.domain.models import Chunk
from core.retrieval.phrase import anchors, choose_page


def test_a_named_phrase_is_kept_and_a_model_code_is_not() -> None:
    asked = "what's the part number of Spring-Return, Neutral of Toro 4000?"

    assert anchors(asked) == ("Spring-Return Neutral",)


def test_a_person_in_a_message_is_the_same_kind_of_phrase() -> None:
    assert anchors('email from Priya Shah about the invoice') == ("Priya Shah",)
    assert anchors("what's on my calendar with Priya Shah") == ("Priya Shah",)


def test_a_question_with_no_name_does_not_pin_a_phrase() -> None:
    assert anchors("what is it") == ()


def test_an_ordinary_phrase_is_kept() -> None:
    assert anchors("when is the budget review") == ("budget review",)


def test_page_27_of_the_manual_yields_to_the_catalogue_row() -> None:
    manual = _chunk("paper:manual", "NEUTRAL-LOCK Center unlocked figure g004532")
    catalogue = _chunk("paper:catalogue", "11 126-8195 1 Spring-Return, Neutral")

    chosen = choose_page([manual], [manual, catalogue], ("Spring-Return Neutral",))

    assert [chunk.doc_id for chunk in chosen] == ["paper:catalogue"]


def test_a_page_that_already_lists_the_part_stays() -> None:
    catalogue = _chunk("paper:catalogue", "11 126-8195 1 Spring-Return, Neutral")

    chosen = choose_page([catalogue], [catalogue], ("Spring-Return Neutral",))

    assert chosen == [catalogue]


def _chunk(doc_id: str, text: str) -> Chunk:
    return Chunk(id=f"{doc_id}:27", doc_id=doc_id, ord=27, text=text, page_start=27, page_end=27)
