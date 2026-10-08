"""The words a passage has to contain.

A question names something, and the rest is how the question is asked.
Ranking by every word prefers a long passage that shares the asking.
These helpers keep a passage that contains the named phrase. The phrase
is not tied to one kind of record: a file, a note, a message, or an event
are the same lookup.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from core.domain.models import Chunk

_WORD = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_QUOTED = re.compile(r"[\"“”']([^\"“”']{2,80})[\"“”']")

# How a question is asked, not what it asks about. "page" is a locator,
# already applied on its own, and is not required to appear in the passage.
_STOP = frozenset(
    """
    a an the of for to in on at by from with about into over under
    and or not my your our me we us
    is are was were be been being do does did can could
    what whats who whose which when where why how
    this that these those it its
    please find search check look again page
    """.split()
)


def anchors(text: str) -> tuple[str, ...]:
    """The one phrase the passage itself should contain.

    Quoted text is used as given. Otherwise the longest run of words that
    are not question scaffolding. One ordinary word is not a phrase, so
    "what is it" does not pin a passage.
    """
    quoted = [piece.strip() for piece in _QUOTED.findall(text) if piece.strip()]
    pool = [*quoted, *_content_runs(text)]
    if not pool:
        return ()
    pool.sort(key=len, reverse=True)
    return (pool[0],)


_COUNT = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")
_PAGE_NUM = re.compile(r"\b(?:page|pg|p)\.?\s+(\d{1,4})\b", re.IGNORECASE)
_CODE = re.compile(r"\d+(?:-\d+)+")


def counts(text: str) -> tuple[str, ...]:
    """Numbers the question states, apart from a page or a hyphenated code.

    A quantity is a token of two or three digits. Embeddings barely notice
    one, so a later pass can require the token itself. No word list is
    involved: the digits are whatever the question typed.
    """
    skip = {match.group(1) for match in _PAGE_NUM.finditer(text)}
    found: list[str] = []
    for match in _COUNT.finditer(_CODE.sub(" ", text)):
        number = match.group(1)
        if number in skip or number in found:
            continue
        found.append(number)
    return tuple(found)


def contains_count(text: str, numbers: Sequence[str]) -> bool:
    folded = text.casefold()
    return any(re.search(rf"(?<!\d){re.escape(number)}(?!\d)", folded) for number in numbers)


def probes(needles: Sequence[str]) -> tuple[str, ...]:
    """One rare token per phrase, for a substring prefilter."""
    found: list[str] = []
    seen: set[str] = set()
    for needle in needles:
        words = _WORD.findall(needle)
        if not words:
            continue
        hyphenated = [word for word in words if "-" in word]
        probe = max(hyphenated or words, key=len).casefold()
        if probe not in seen:
            seen.add(probe)
            found.append(probe)
    return tuple(found)


def contains_anchor(text: str, needles: Sequence[str]) -> bool:
    return any(_phrase_in(text, needle) for needle in needles)


def matching(chunks: Sequence[Chunk], needles: Sequence[str]) -> list[Chunk]:
    return [chunk for chunk in chunks if contains_anchor(chunk.text, needles)]


def choose_page(
    focused: Sequence[Chunk],
    wider: Sequence[Chunk],
    needles: Sequence[str],
) -> list[Chunk]:
    """The named page, or another source's copy of that page that has the phrase.

    The same title can belong to two files, and the same page number can
    belong to the wrong one. A message or an event has no page, and this
    returns the focused passages unchanged when no phrase was named.
    """
    if not needles:
        return list(focused)
    matched = _unique(chunk for chunk in focused if contains_anchor(chunk.text, needles))
    if matched:
        return matched
    matched = _unique(chunk for chunk in wider if contains_anchor(chunk.text, needles))
    return matched or list(focused)


def _content_runs(text: str) -> list[str]:
    runs: list[list[str]] = []
    current: list[str] = []
    for token in _WORD.findall(text):
        if token.casefold() in _STOP:
            _close(current, runs)
            current = []
            continue
        current.append(token)
    _close(current, runs)
    phrases: list[str] = []
    for run in runs:
        if len(run) >= 2 or _distinctive(run[0]):
            phrases.append(" ".join(run))
    return phrases


def _close(current: list[str], runs: list[list[str]]) -> None:
    if current:
        runs.append(list(current))


def _distinctive(token: str) -> bool:
    """A hyphenated name or a token that mixes letters and digits. A plain word is not."""
    if "-" in token and len(token) >= 5:
        return True
    letters = any(character.isalpha() for character in token)
    digits = any(character.isdigit() for character in token)
    return letters and digits and len(token) >= 4


def _phrase_in(text: str, phrase: str) -> bool:
    words = [word.casefold() for word in _WORD.findall(phrase)]
    if not words:
        return False
    folded = text.casefold()
    pattern = r"\b" + r"\W+".join(re.escape(word) for word in words)
    return re.search(pattern, folded) is not None


def _unique(chunks: Iterable[Chunk]) -> list[Chunk]:
    found: list[Chunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        found.append(chunk)
    return found
