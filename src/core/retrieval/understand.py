"""Rewrite a question into a few short search phrases.

The rules in `phrase` keep a quoted name, a part number, and a stated
count. Wording is not a rule. A local model proposes the phrases a
passage might use for the same fact, and the index decides which
passages exist. The model is not asked to answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from core.retrieval.phrase import anchors, counts

_WORD = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_SYSTEM = """You turn a question into search probes for a private library.
Reply with JSON only, in this shape: {"probes": ["...", "..."]}

probes are 2 to 4 short phrases a passage might contain for the same fact.
When the question spells a multi-word name out, also offer a shorter form a passage might use.
When the question uses a short form, also offer the spelled-out form.
Each probe is at most 8 words.
Do not answer the question.
Do not name a document, a title, or an author.
Do not copy the question verbatim."""


class ProbeSource(Protocol):
    async def complete(
        self, messages: Sequence[dict[str, str]], *, temperature: float = 0.0
    ) -> str: ...


class ProbeParser(Protocol):
    async def probes(self, question: str, *, titles: Sequence[str]) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class QueryPlan:
    probes: tuple[str, ...]
    counts: tuple[str, ...]
    # Set when the passage must contain this string, as for a part name.
    # Empty when a stated count should be matched instead of the whole phrase.
    literal: str | None


def fallback_plan(question: str) -> QueryPlan:
    """A plan that needs no model: the named phrase, plus any stated count."""
    phrase = anchors(question)
    numbers = counts(question)
    literal = phrase[0] if phrase and not numbers else None
    if phrase:
        probes = phrase
    elif question.strip():
        probes = (question.strip(),)
    else:
        probes = ()
    return QueryPlan(probes, numbers, literal)


class LlmQueryParser:
    """Cached probe rewrite. A failure leaves the caller on the rule plan."""

    def __init__(self, source: ProbeSource) -> None:
        self._source = source
        self._cache: dict[str, str] = {}

    async def probes(self, question: str, *, titles: Sequence[str]) -> tuple[str, ...]:
        key = " ".join(question.split()).casefold()
        if not key:
            return ()
        raw = self._cache.get(key)
        if raw is None:
            try:
                raw = await self._source.complete(
                    [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": question.strip()},
                    ],
                    temperature=0.0,
                )
            except Exception:
                return ()
            self._cache[key] = raw
            if len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
        return _probes(raw, question, titles)


def _probes(raw: str, question: str, titles: Sequence[str]) -> tuple[str, ...]:
    payload = _object(raw)
    if payload is None:
        return ()
    found = payload.get("probes")
    if isinstance(found, str):
        found = [found]
    if not isinstance(found, list):
        return ()
    leads = _unique_leads(titles)
    asked = {word.casefold() for word in _WORD.findall(question)}
    question_key = " ".join(question.split()).casefold()
    kept: list[str] = []
    seen: set[str] = set()
    for item in found:
        if not isinstance(item, str):
            continue
        probe = " ".join(item.split())
        words = _WORD.findall(probe)
        key = probe.casefold()
        if not probe or key in seen or key == question_key:
            continue
        if not 1 <= len(words) <= 8 or not 2 <= len(probe) <= 80:
            continue
        if any(leads.get(word.casefold()) == 1 and word.casefold() not in asked for word in words):
            continue
        seen.add(key)
        kept.append(probe)
        if len(kept) == 4:
            break
    return tuple(kept)


def _unique_leads(titles: Sequence[str]) -> dict[str, int]:
    """First word of each title, counted so a shared word is not a name."""
    counts: dict[str, int] = {}
    for title in titles:
        words = _WORD.findall(title)
        if not words or len(words[0]) < 4:
            continue
        lead = words[0].casefold()
        counts[lead] = counts.get(lead, 0) + 1
    return counts


def _object(raw: str) -> dict[str, object] | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
