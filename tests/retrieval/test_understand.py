"""A probe rewrite must not invent a title, and a broken reply adds nothing."""

import asyncio

from core.retrieval.understand import LlmQueryParser, fallback_plan


def test_a_stated_count_is_not_treated_as_a_literal_phrase() -> None:
    plan = fallback_plan("there are 12 readings in one of the papers, which paper is it?")

    assert plan.counts == ("12",)
    assert plan.literal is None
    assert plan.probes


def test_a_part_name_stays_a_literal_phrase() -> None:
    plan = fallback_plan("what's the part number of Spring-Return, Neutral of Toro 4000?")

    assert plan.literal == "Spring-Return Neutral"
    assert plan.counts == ()


def test_a_probe_that_names_another_document_is_dropped() -> None:
    parser = LlmQueryParser(
        _Reply('{"probes": ["alpha beta", "HADD result", "the stated count"]}')
    )

    probes = asyncio.run(
        parser.probes(
            "which paper states 12 readings?",
            titles=("HADD: High-Accuracy Detection", "AROD: Adaptive Detection"),
        )
    )

    assert probes == ("alpha beta", "the stated count")


def test_a_reply_that_is_not_json_adds_no_probes() -> None:
    parser = LlmQueryParser(_Reply("I think the paper is somewhere."))

    probes = asyncio.run(parser.probes("which paper states 12 readings?", titles=()))

    assert probes == ()


def test_the_same_question_is_not_sent_twice() -> None:
    source = _Reply('{"probes": ["alpha beta"]}')
    parser = LlmQueryParser(source)

    first = asyncio.run(parser.probes("which paper states 12 readings?", titles=()))
    second = asyncio.run(parser.probes("which paper states 12 readings?", titles=()))

    assert first == second == ("alpha beta",)
    assert source.calls == 1


class _Reply:
    def __init__(self, body: str) -> None:
        self._body = body
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]], *, temperature: float = 0) -> str:
        self.calls += 1
        return self._body
