"""Decide which document a question is about before searching.

Follow-ups such as "this paper" carry no title. The client sends the
document the previous turn cited; this module keeps the search there
unless the question names a different document or asks to look across the
library. A product code such as "toro4000" is shared by a whole folder, so
every document in that family is searched together, and a near-miss such
as "tor04000" stays on the same family. A question that asks which
documents name a person is answered from those records, and the focused
document does not capture it. Author, year, venue, and DOI of one document
are read from its record rather than from whatever chunks happen to match
the words.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.retrieval.records import people_asked
from core.store import IndexedDocument

Kind = Literal["metadata", "content", "library", "records"]

_COMPARE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|other papers|other approaches|"
    r"across (?:the )?(?:papers|library))\b",
    re.IGNORECASE,
)
_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authors",
        re.compile(r"\b(authors?|who wrote|written by|who (?:is|are) the authors?)\b", re.I),
    ),
    (
        "year",
        re.compile(r"\b(what year|which year|publication year|when was .{0,40}?published)\b", re.I),
    ),
    (
        "venue",
        re.compile(
            r"\b(venue|where (?:was|is) .{0,30}?published|which (?:journal|conference))\b", re.I
        ),
    ),
    ("doi", re.compile(r"\bdoi\b", re.I)),
    ("title", re.compile(r"\b(full title|paper'?s title|what(?:'s| is) the title)\b", re.I)),
)
_LEAD = re.compile(r"[A-Za-z0-9]+")
_PAGE = re.compile(r"\b(?:page|pg|p)\.?\s+(\d{1,4})\b", re.IGNORECASE)
# "Which paper uses 12 models" is a library lookup. The document cited on
# the previous turn is the wrong place to search, and it stays wrong until
# the title is typed.
_IDENTIFY = re.compile(
    r"\b(?:which|what)\s+(?:paper|article|document|file)\b"
    r"|\b(?:one|some)\s+of\s+(?:the\s+)?(?:papers?|articles?|documents?|files?)\b",
    re.IGNORECASE,
)
# o/0 and l/i/1 are the swaps that show up when a model code is typed by hand.
_FOLD = str.maketrans({"o": "0", "l": "1", "i": "1"})


@dataclass(frozen=True, slots=True)
class Decision:
    kind: Kind
    doc_ids: tuple[str, ...]
    field: str | None = None
    # 1-based place in the author list. -1 means the last author.
    author_index: int | None = None
    # People a "which documents" question named. Empty unless kind is records.
    people: tuple[str, ...] = ()
    # Set when the question names a page. Retrieval stays on that page.
    page: int | None = None


def decide(
    question: str,
    *,
    focus_doc_id: str | None,
    papers: Sequence[IndexedDocument],
) -> Decision:
    """Scope and intent for one turn. Empty doc_ids means the whole library."""
    known = {paper.id for paper in papers}
    focus = focus_doc_id if focus_doc_id in known else None
    named = _named_papers(question, papers)
    field = _metadata_field(question)
    author_index = _author_index(question) if field == "authors" else None

    if _COMPARE.search(question):
        ids = tuple(paper.id for paper in named)
        if len(ids) >= 2:
            return Decision("content", ids)
        return Decision("library", ())

    people = people_asked(question, papers)
    if people:
        return Decision("records", (), people=people)

    page = _asked_page(question)
    family = _product_family(question, papers)
    if page is not None:
        scope = _page_scope(named, focus, family)
        if scope:
            return Decision("content", scope, page=page)
    if family:
        return Decision("content", tuple(paper.id for paper in family))
    if _IDENTIFY.search(question) and not named and field is None:
        return Decision("library", ())

    target = _target(named, focus)
    if field and target:
        return Decision("metadata", (target,), field, author_index)
    if target:
        return Decision("content", (target,))
    if field and named:
        return Decision("metadata", (named[0].id,), field, author_index)
    return Decision("library", ())


def metadata_answer(
    document: IndexedDocument, field: str, *, index: int | None = None
) -> str | None:
    """A sentence from the stored record, or None when that field is empty."""
    title = document.title
    if field == "authors" and document.authors:
        if index is None:
            return f"{title} is by {', '.join(document.authors)}."
        return _author_at(title, document.authors, index)
    if field == "year" and document.year:
        return f"{title} was published in {document.year}."
    if field == "venue" and document.venue:
        return f"{title} was published in {document.venue}."
    if field == "doi" and document.doi:
        return f"The DOI of {title} is {document.doi}."
    if field == "title" and title:
        return f"The paper is titled “{title}”."
    return None


def _target(named: Sequence[IndexedDocument], focus: str | None) -> str | None:
    """The paper this question is about.

    A name in the question wins over the paper carried from the last turn,
    so "how does Corun ..." leaves AROD behind. Naming the focused paper
    keeps it.
    """
    others = [paper.id for paper in named if paper.id != focus]
    if others:
        return others[0]
    if named:
        return named[0].id
    return focus


_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "6th": 6,
    "seventh": 7,
    "7th": 7,
    "eighth": 8,
    "8th": 8,
    "last": -1,
}
_ORDINAL_WORD = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
}
_AUTHOR_PLACE = re.compile(
    r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|sixth|6th|"
    r"seventh|7th|eighth|8th|last)\s+authors?\b",
    re.IGNORECASE,
)


def _author_index(question: str) -> int | None:
    match = _AUTHOR_PLACE.search(question)
    if match is None:
        return None
    return _ORDINALS[match.group(1).lower()]


def _author_at(title: str, authors: tuple[str, ...], index: int) -> str:
    slot = len(authors) if index < 0 else index
    word = "last" if index < 0 else _ORDINAL_WORD.get(slot, f"{slot}th")
    if slot < 1 or slot > len(authors):
        noun = "author" if len(authors) == 1 else "authors"
        return f"{title} lists {len(authors)} {noun}, so there is no {word} author."
    return f"The {word} author of {title} is {authors[slot - 1]}."


def _metadata_field(question: str) -> str | None:
    field = next((name for name, pattern in _FIELDS if pattern.search(question)), None)
    if field is None:
        return None
    words = question.split()
    if len(words) <= 18:
        return field
    if re.match(r"^(who|what|when|where|which)\b", question.strip(), re.IGNORECASE):
        return field
    return None


def _asked_page(question: str) -> int | None:
    match = _PAGE.search(question)
    if match is None:
        return None
    page = int(match.group(1))
    return page if page >= 1 else None


def _page_scope(
    named: Sequence[IndexedDocument],
    focus: str | None,
    family: Sequence[IndexedDocument],
) -> tuple[str, ...]:
    """The documents a named page belongs to. Empty when no document is known."""
    if len(named) == 1:
        return (named[0].id,)
    family_ids = {paper.id for paper in family}
    if family:
        picked = tuple(paper.id for paper in named if paper.id in family_ids)
        if len(picked) == 1:
            return picked
        if focus and focus in family_ids:
            return (focus,)
        return tuple(paper.id for paper in family)
    if focus:
        return (focus,)
    if named:
        return (named[0].id,)
    return ()


def _product_family(
    question: str, papers: Sequence[IndexedDocument]
) -> list[IndexedDocument]:
    """Every document that carries a model code typed in the question.

    The code is read from the file path and the filename, which is where
    "toro4000" lives even when the page text never spells it. Letter/digit
    lookalikes are folded so "tor04000" and "toro4000" select one family.
    """
    asked = _product_codes(question)
    if not asked:
        return []
    found: list[IndexedDocument] = []
    for paper in papers:
        label = f"{paper.id} {paper.filename} {paper.title}"
        tokens = {_fold(word) for word in _LEAD.findall(label)}
        if any(_same_code(token, code) for code in asked for token in tokens):
            found.append(paper)
    return found


def _product_codes(question: str) -> set[str]:
    """Model codes: one token with letters and digits, or "toro 4000"."""
    words = _LEAD.findall(question)
    codes: set[str] = set()
    for index, word in enumerate(words):
        if _is_code(word):
            codes.add(_fold(word))
        elif (
            index + 1 < len(words)
            and word.isalpha()
            and 4 <= len(word) <= 12
            and words[index + 1].isdigit()
            and len(words[index + 1]) >= 3
        ):
            codes.add(_fold(word + words[index + 1]))
    return codes


def _is_code(word: str) -> bool:
    letters = any(char.isalpha() for char in word)
    digits = any(char.isdigit() for char in word)
    return len(word) >= 5 and letters and digits


def _same_code(token: str, code: str) -> bool:
    """`toro4000` matches itself and `toro4000pro`, not `toro40001`."""
    if token == code:
        return True
    return token.startswith(code) and token[len(code) :].isalpha()


def _fold(word: str) -> str:
    return word.lower().translate(_FOLD)


def _named_papers(question: str, papers: Sequence[IndexedDocument]) -> list[IndexedDocument]:
    """Papers whose short name appears in the question, and nowhere else."""
    asked = {word.lower() for word in _LEAD.findall(question) if len(word) >= 4}
    if not asked:
        return []
    keys = {paper.id: _lead_keys(paper) for paper in papers}
    shared: dict[str, int] = {}
    for group in keys.values():
        for key in group:
            shared[key] = shared.get(key, 0) + 1
    found = []
    for paper in papers:
        distinctive = {key for key in keys[paper.id] if shared.get(key) == 1}
        if distinctive & asked:
            found.append(paper)
    return found


def _lead_keys(paper: IndexedDocument) -> set[str]:
    keys: set[str] = set()
    for source in (paper.title, paper.filename):
        words = _LEAD.findall(source)
        if words and len(words[0]) >= 4:
            keys.add(words[0].lower())
        keys.update(word.lower() for word in words[:8] if word.isupper() and len(word) >= 3)
    return keys
