"""A follow-up keeps the question it is answering."""

from core.domain.models import Chunk
from core.retrieval.answer import build_messages
from core.retrieval.hybrid import Retrieved


def test_a_follow_up_keeps_the_earlier_question() -> None:
    hit = Retrieved(
        chunk=Chunk(
            id="paper:catalogue:27",
            doc_id="paper:catalogue",
            ord=27,
            text="11 126-8195 1 Spring-Return, Neutral",
            page_start=27,
            page_end=27,
        ),
        score=0.0,
        keyword_rank=1,
        vector_rank=None,
    )

    messages = build_messages(
        "look for it on page 27",
        [hit],
        {},
        prior_question="what's the part number of Spring-Return, Neutral of Toro 4000?",
    )

    asked = messages[1]["content"]
    assert "what's the part number of Spring-Return, Neutral" in asked
    assert "Follow-up: look for it on page 27" in asked
    assert "126-8195" in asked


def test_a_question_that_names_its_subject_drops_the_earlier_question() -> None:
    hit = Retrieved(
        chunk=Chunk(
            id="paper:hadd:29",
            doc_id="paper:hadd",
            ord=29,
            text="After extending the 12 ML models",
            page_start=14,
            page_end=14,
        ),
        score=0.0,
        keyword_rank=1,
        vector_rank=None,
    )

    messages = build_messages(
        "there are 12 machine learning models are used in one of the paper, which paper is it?",
        [hit],
        {},
        prior_question="any article talk about L-K method?",
    )

    asked = messages[1]["content"]
    assert "L-K" not in asked
    assert "which paper is it?" in asked
