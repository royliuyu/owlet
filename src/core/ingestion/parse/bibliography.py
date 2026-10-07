"""Authors, year, venue, and DOI from the first page of a paper.

Chunk search cannot answer "who wrote this": the byline is a line under
the title, and the question does not share its words. The record is read
once, at index time, and stored on the document.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import pymupdf

# Bump when the extractor changes so the next index refreshes stored records
# without rebuilding chunks.
BIBLIOGRAPHY_VERSION = 1

_ABSTRACT = re.compile(r"^abstract\b", re.IGNORECASE)
_NOT_A_BYLINE = re.compile(
    r"@|department|university|correspondence|index terms|^keywords\b|"
    r"^citation\b|^received\b|^published\b|^accepted\b|^revised\b|"
    r"^copyright\b|licensee|creativecommons",
    re.IGNORECASE,
)
_NAME_STOP = frozenset(
    "a an and at by for from in of on or the to via with".split()
)
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_CONFERENCE = re.compile(
    r"((?:19|20)\d{2}.{0,12})?(?:IEEE\s+)?.{0,80}?\b(?:Conference|Symposium|Workshop)\b[^|]{0,60}",
    re.IGNORECASE,
)
_JOURNAL = re.compile(r"\b([A-Z][A-Za-z]{2,})\s+((?:19|20)\d{2})\s*,\s*\d+")


def read_bibliography(content: bytes) -> dict[str, object]:
    """A record with a version, safe to store even when a field is missing."""
    found = _empty()
    if not content:
        return found
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception:
        return found
    with document:
        meta = document.metadata or {}
        page_lines = _first_page_lines(document)
        page_text = document[0].get_text() if document.page_count else ""
    texts = [text for text, _size in page_lines]
    title = " ".join(str(meta.get("title") or "").split())
    if not title:
        title = _title_from_lines(page_lines)
    authors = split_authors(str(meta.get("author") or ""))
    if not authors:
        authors = authors_before_abstract(page_lines)
    venue = venue_from_lines(texts)
    year = year_from_lines(texts) or _year_in(venue)
    doi = doi_from_text(page_text)
    found.update(title=title, authors=authors, year=year, venue=venue, doi=doi)
    return found


def split_authors(text: str) -> list[str]:
    """'Yu Liu, Anurag Andhare, and Kyoung-Don Kang *' → three names."""
    cleaned = text.replace("*", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned or _NOT_A_BYLINE.search(cleaned):
        return []
    parts = re.split(r",|\band\b", cleaned)
    names = []
    for part in parts:
        name = part.strip(" ,;.")
        if _looks_like_name(name):
            names.append(name)
    return names[:8]


def authors_before_abstract(lines: Sequence[tuple[str, float]]) -> list[str]:
    """The byline sits under the title and above the abstract."""
    if not lines:
        return []
    biggest = max((size for _text, size in lines), default=0.0)
    title_floor = biggest * 0.85 if biggest else 0.0
    passed_title = title_floor <= 0
    for text, size in lines:
        if not passed_title:
            if size >= title_floor:
                passed_title = True
            continue
        if _ABSTRACT.match(text):
            break
        if size >= title_floor:
            continue
        names = split_authors(text)
        if names and ("," in text or re.search(r"\band\b", text, re.IGNORECASE)):
            return names
    return []


def venue_from_lines(lines: Sequence[str]) -> str:
    for text in lines:
        flat = " ".join(text.split())
        match = _CONFERENCE.search(flat)
        if match and _YEAR.search(flat):
            return " ".join(match.group(0).split()).strip(" -|")
    for text in lines:
        flat = " ".join(text.split())
        match = _JOURNAL.search(flat)
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return ""


def year_from_lines(lines: Sequence[str]) -> int | None:
    """Prefer a year that is part of the publication line, not a citation."""
    for text in lines:
        flat = " ".join(text.split())
        if not re.search(r"©|copyright|published", flat, re.IGNORECASE):
            continue
        years = [int(year) for year in _YEAR.findall(flat)]
        if years:
            return years[-1]
    return None


def doi_from_text(text: str) -> str:
    match = _DOI.search(text)
    if match is None:
        return ""
    return match.group(1).rstrip(").,;")


def _empty() -> dict[str, object]:
    return {
        "v": BIBLIOGRAPHY_VERSION,
        "title": "",
        "authors": [],
        "year": None,
        "venue": "",
        "doi": "",
    }


def _first_page_lines(document: pymupdf.Document) -> list[tuple[str, float]]:
    if document.page_count == 0:
        return []
    found: list[tuple[float, float, str, float]] = []
    for block in document[0].get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = " ".join("".join(span.get("text", "") for span in spans).split())
            if not text:
                continue
            sizes = [float(span.get("size", 0.0)) for span in spans if span.get("text")]
            x0, y0, _x1, _y1 = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
            found.append((y0, x0, text, max(sizes) if sizes else 0.0))
    found.sort()
    return [(text, size) for _y, _x, text, size in found]


def _title_from_lines(lines: Sequence[tuple[str, float]]) -> str:
    if not lines:
        return ""
    biggest = max(size for _text, size in lines)
    if biggest <= 0:
        return ""
    parts = [text for text, size in lines if size >= biggest * 0.85]
    return " ".join(parts[:4])


def _looks_like_name(name: str) -> bool:
    if not name or ":" in name or any(char.isdigit() for char in name):
        return False
    words = [word.strip(".,") for word in name.split() if word.strip(".,")]
    if not 2 <= len(words) <= 4:
        return False
    if any(word.lower() in _NAME_STOP for word in words):
        return False
    return all(word[:1].isupper() for word in words)


def _year_in(text: str) -> int | None:
    match = _YEAR.search(text)
    return int(match.group(0)) if match else None
