"""List documents by the people they are filed under.

Passage search finds pages that mention a name. A question that asks which
documents a person belongs to is a different lookup: each source contributes
the names it stores, and the answer is that list. Papers contribute authors.
A later source adds its own names in `listed_people` — mail participants,
event attendees — without a new question route.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from core.store import IndexedDocument

# A request for the set of documents, not a question about one of them.
_LIST = re.compile(
    r"("
    r"\bsearch the library\b"
    r"|\b(?:written|authored)\s+by\b"
    r"|\b(?:papers|documents|titles|works|files)\s+by\b"
    r"|\b(?:what|which)\s+(?:papers|documents|titles|works|files)\b"
    r"|\b(?:list|find|show)\b.{0,48}\b(?:papers|documents|titles|works|files)\b"
    r"|\bwhat (?:did|has|have)\b.{0,80}\b(?:write|wrote|written)\b"
    r")",
    re.IGNORECASE,
)
_CUES = (
    re.compile(r"\b(?:written|authored)\s+by\s+(.+)", re.IGNORECASE),
    re.compile(r"\b(?:papers|documents|titles|works|files)\s+by\s+(.+)", re.IGNORECASE),
    re.compile(r"\bauthors?\s+(.+)", re.IGNORECASE),
    re.compile(
        r"\b(?:what|which)\b.{0,40}?\b(?:did|has|have)\s+(.+?)\s+(?:write|wrote|written)\b",
        re.IGNORECASE,
    ),
)
_STOP = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "by",
        "in",
        "library",
        "of",
        "or",
        "paper",
        "papers",
        "that",
        "the",
        "this",
        "title",
        "titles",
    }
)
_NAME_WORD = re.compile(r"[A-Za-z][\w.'’-]*|[\u4e00-\u9fff]{2,4}")


def listed_people(document: IndexedDocument) -> tuple[str, ...]:
    """Names this document is filed under, in display form."""
    return document.authors


def people_asked(question: str, documents: Sequence[IndexedDocument]) -> tuple[str, ...] | None:
    """The people a list question names, or None when this is not that question.

    A name stored on any document wins, so "yu liu" matches the record "Yu Liu".
    A name that is not stored yet is still returned, and the lookup then says
    the library has no document for them. A short name that is actually a
    document title is left for the paper-name route.
    """
    if not _asks_for_records(question):
        return None
    mentioned = _mentioned(question, _known_people(documents))
    if mentioned:
        return mentioned
    explicit = _explicit_name(question)
    if explicit and not _names_a_document(explicit, documents):
        return (explicit,)
    return None


def select_records(
    documents: Sequence[IndexedDocument],
    people: Sequence[str],
    *,
    sources: Sequence[str] | None = None,
) -> list[IndexedDocument]:
    """Documents filed under every named person, newest year first."""
    found = [
        document
        for document in documents
        if (sources is None or document.source in sources)
        and all(_matches(document, person) for person in people)
    ]
    return sorted(found, key=lambda document: (-(document.year or 0), document.title.casefold()))


def records_answer(people: Sequence[str], documents: Sequence[IndexedDocument]) -> str:
    """One sentence whose bracket numbers are the citation list."""
    who = _who(people)
    if not documents:
        return f"No document in the library lists {who}."
    parts = []
    for number, document in enumerate(documents, start=1):
        year = f" ({document.year})" if document.year else ""
        parts.append(f"[{number}] {document.title}{year}")
    noun = "document" if len(documents) == 1 else "documents"
    listed = ", ".join(parts)
    return f"{who} is listed on {len(documents)} {noun}: {listed}."


def _asks_for_records(question: str) -> bool:
    if _LIST.search(question) is None:
        return False
    if len(question.split()) <= 28:
        return True
    return bool(
        re.match(r"^(list|which|what|who|find|show|search)\b", question.strip(), re.IGNORECASE)
    )


def _known_people(documents: Sequence[IndexedDocument]) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for document in documents:
        for name in listed_people(document):
            key = name.casefold()
            if key in seen or len(name) < 2:
                continue
            seen.add(key)
            found.append(name)
    return tuple(found)


def _mentioned(question: str, names: Sequence[str]) -> tuple[str, ...]:
    kept: list[str] = []
    for name in sorted(names, key=len, reverse=True):
        if any(name.casefold() in earlier.casefold() for earlier in kept):
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)
        if pattern.search(question):
            kept.append(name)
    return tuple(kept)


def _explicit_name(question: str) -> str | None:
    for pattern in _CUES:
        match = pattern.search(question)
        if match is None:
            continue
        name = _trim_name(match.group(1))
        if name:
            return name
    return None


def _trim_name(tail: str) -> str | None:
    words: list[str] = []
    for word in tail.split():
        bare = word.strip(" ,.;:!?\"'")
        if not bare or bare.casefold() in _STOP or _NAME_WORD.fullmatch(bare) is None:
            break
        if bare[:1].islower() and not _cjk(bare):
            break
        words.append(bare)
        if len(words) == 4:
            break
    if not words:
        return None
    return " ".join(words)


def _cjk(word: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", word))


def _names_a_document(name: str, documents: Sequence[IndexedDocument]) -> bool:
    needle = name.casefold()
    for document in documents:
        if document.title.casefold().startswith(needle):
            return True
        if document.filename.casefold().startswith(needle):
            return True
    return False


def _matches(document: IndexedDocument, person: str) -> bool:
    needle = person.casefold()
    for name in listed_people(document):
        folded = name.casefold()
        if folded == needle:
            return True
        last = folded.split()[-1] if folded.split() else ""
        if len(needle) >= 3 and needle == last:
            return True
    return False


def _who(people: Sequence[str]) -> str:
    names = list(people)
    if not names:
        return "That person"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
