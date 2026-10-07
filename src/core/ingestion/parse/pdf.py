"""PDF text and layout extraction.

PyMuPDF rather than pypdf, because citations have to point back at a
rectangle on the page and pypdf only ever yields a flat string. Each
line arrives with a box and a font size; headings are then whatever
stands out from the body either typographically or lexically.

Docling would read structure better, and would slot in here as another
Parser, but it carries a torch-sized dependency and takes seconds per
page on CPU. This stays in milliseconds, which matters when a library
of papers is indexed in one pass.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from statistics import median

import pymupdf

from core.domain.errors import ParseError
from core.domain.models import BBox
from core.ingestion.parse.base import LayoutBlock, PageText, ParsedDocument

_HYPHEN_BREAK = re.compile(r"-\n(?=\w)")
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")
_NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
# Only names that are sections when they stand alone. "Model", "Design" and
# "Analysis" are table and figure captions far more often than headings, and
# when they are headings they are numbered, so _NUMBERED already has them.
_NAMED = re.compile(
    r"^(abstract|introduction|related work|background|preliminaries|methods|"
    r"methodology|experiments?|evaluation|results?|discussion|ablation|"
    r"limitations?|conclusions?|future work|references|bibliography|"
    r"acknowledge?ments?|appendix|supplementary)\b",
    re.IGNORECASE,
)

# A heading's font is meaningfully larger than the body's, not a rounding
# difference. Papers that set headings in bold at body size are caught by
# the lexical rules instead.
_HEADING_RATIO = 1.12

# Headings are set in title case and prose is not, which separates the two
# even when they share a font. Stop words stay lowercase in title case, so
# they are not evidence either way.
_TITLE_CASE_MIN = 0.65
_STOP_WORDS = frozenset(
    "a an and as at by for from in of on or the to via with".split()
)

# A named heading is "Related Work", not a paragraph that happens to open
# with the word. Numbered ones may be long: "5. CNN Models, Datasets, ...".
_NAMED_MAX_WORDS = 5

# Headings are sometimes set a hair under the body size, never well under.
_BODY_FLOOR = 0.95

# Clause joiners and operators belong to sentences, equations and reference
# lists. No heading contains one.
_NOT_IN_HEADINGS = (";", "=", "//")

_WORDS = re.compile(r"[\s,:()\[\]]+")


class PdfParser:
    format = "pdf"

    def parse(self, content: bytes) -> ParsedDocument:
        if not content:
            raise ParseError("PDF is empty")
        try:
            document = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise ParseError("Could not read PDF") from exc
        with document:
            if document.needs_pass and not document.authenticate(""):
                raise ParseError("PDF is encrypted")
            try:
                lines = _lines(document)
                pages = _pages(document)
            except ParseError:
                raise
            except Exception as exc:
                raise ParseError("Could not read PDF") from exc
        body = _body_size(lines)
        return ParsedDocument(pages=pages, blocks=_group(lines, body))


class _Line:
    __slots__ = ("text", "page", "size", "box")

    def __init__(self, text: str, page: int, size: float, box: BBox) -> None:
        self.text = text
        self.page = page
        self.size = size
        self.box = box


def _pages(document: pymupdf.Document) -> list[PageText]:
    pages: list[PageText] = []
    for index, page in enumerate(document, start=1):
        pages.append(PageText(page=index, text=normalize_page_text(page.get_text())))
    return pages


def _lines(document: pymupdf.Document) -> list[_Line]:
    lines: list[_Line] = []
    for index, page in enumerate(document, start=1):
        width = page.rect.width or 1.0
        height = page.rect.height or 1.0
        payload = page.get_text("dict")
        for block in payload.get("blocks", []):
            if block.get("type") != 0:
                continue  # image
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans)
                text = " ".join(text.split())
                if not text:
                    continue
                sizes = [float(span.get("size", 0.0)) for span in spans if span.get("text")]
                x0, y0, x1, y1 = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                lines.append(
                    _Line(
                        text=text,
                        page=index,
                        size=max(sizes) if sizes else 0.0,
                        box=BBox(
                            page=index,
                            x0=_clamp(x0 / width),
                            y0=_clamp(y0 / height),
                            x1=_clamp(x1 / width),
                            y1=_clamp(y1 / height),
                        ),
                    )
                )
    return lines


def _body_size(lines: list[_Line]) -> float:
    """The size most of the text is actually set in.

    A median over lines is dragged down by references and captions, which
    are numerous and short; weighting by characters finds the size the body
    is set in, which is what a heading has to stand out from.
    """
    weight: dict[float, int] = {}
    for line in lines:
        if line.size > 0:
            key = round(line.size, 1)
            weight[key] = weight.get(key, 0) + len(line.text)
    return max(weight, key=lambda size: weight[size]) if weight else 0.0


def _group(lines: list[_Line], body_size: float) -> list[LayoutBlock]:
    """Fold lines into headings and paragraphs, keeping their boxes."""
    blocks: list[LayoutBlock] = []
    buffer: list[_Line] = []

    def flush() -> None:
        if not buffer:
            return
        blocks.append(_paragraph(buffer))
        buffer.clear()

    for line in lines:
        if looks_like_heading(line.text, size=line.size, body_size=body_size):
            flush()
            blocks.append(
                LayoutBlock(
                    kind="heading",
                    text=line.text,
                    page=line.page,
                    page_end=line.page,
                    bboxes=[line.box],
                    font_size=line.size,
                )
            )
            continue
        buffer.append(line)
    flush()
    return _merge_page_breaks(blocks)


def _paragraph(lines: list[_Line]) -> LayoutBlock:
    return LayoutBlock(
        kind="paragraph",
        text=_join(lines),
        page=lines[0].page,
        page_end=lines[-1].page,
        bboxes=_merge_boxes(line.box for line in lines),
        font_size=median([line.size for line in lines]) if lines else 0.0,
    )


def _join(lines: list[_Line]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line.text
        elif out.endswith("-"):
            out = out[:-1] + line.text
        else:
            out = f"{out} {line.text}"
    return out


def looks_like_heading(text: str, *, size: float, body_size: float) -> bool:
    """Large type alone is not enough.

    Papers set captions, figure labels, equations and reference entries
    above the body size, and set section headings at it. So a line has to
    read like a title as well: short, title-cased, and not a sentence.
    """
    if not text or len(text) > 90 or len(text.split()) > 12:
        return False
    if text[0].islower() or text.endswith((".", ",", ";", ":")):
        return False
    if any(mark in text for mark in _NOT_IN_HEADINGS):
        return False
    if not _has_word(text):
        return False  # running heads and folios such as "14 of 19"
    if not _title_cased(text):
        return False
    if _NAMED.match(text):
        # Set at body size or above. A caption reading "Results" is smaller.
        return len(text.split()) <= _NAMED_MAX_WORDS and size >= body_size * _BODY_FLOOR
    if _NUMBERED.match(text):
        return True  # a section number is evidence enough; size varies
    if body_size <= 0 or size < body_size * _HEADING_RATIO:
        return False
    letters = sum(1 for char in text if char.isalpha())
    return letters >= 3


def _title_cased(text: str) -> bool:
    """Capitalisation of the words that carry meaning.

    Any capital counts, not just a leading one, so acronym-shaped titles
    like "mAP" read as headings while "stream" and "return" do not.
    """
    content = [
        word
        for word in _WORDS.split(text)
        if word and word[0].isalpha() and word.lower() not in _STOP_WORDS
    ]
    if not content:
        return False
    capitals = sum(1 for word in content if any(char.isupper() for char in word))
    return capitals / len(content) >= _TITLE_CASE_MIN


def _has_word(text: str) -> bool:
    """A title names something; a folio is digits and filler."""
    return any(len(word) >= 3 and word.isalpha() for word in re.split(r"\W+", text))


def _merge_boxes(boxes: Iterable[BBox]) -> list[BBox]:
    """One rectangle per page, so a highlight is a few shapes not hundreds."""
    by_page: dict[int, BBox] = {}
    for box in boxes:
        current = by_page.get(box.page)
        if current is None:
            by_page[box.page] = box
            continue
        by_page[box.page] = BBox(
            page=box.page,
            x0=min(current.x0, box.x0),
            y0=min(current.y0, box.y0),
            x1=max(current.x1, box.x1),
            y1=max(current.y1, box.y1),
        )
    return [by_page[page] for page in sorted(by_page)]


def _merge_page_breaks(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """A sentence running over a page break is still one paragraph."""
    if not blocks:
        return []
    merged = [blocks[0]]
    for block in blocks[1:]:
        previous = merged[-1]
        continues = (
            previous.kind == "paragraph"
            and block.kind == "paragraph"
            and block.page == previous.page_end + 1
            and _SENTENCE_END.search(previous.text) is None
        )
        if not continues:
            merged.append(block)
            continue
        merged[-1] = LayoutBlock(
            kind="paragraph",
            text=f"{previous.text} {block.text}",
            page=previous.page,
            page_end=block.page_end,
            bboxes=_merge_boxes([*previous.bboxes, *block.bboxes]),
            font_size=previous.font_size,
        )
    return merged


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def normalize_page_text(text: str) -> str:
    """Repair line-break hyphenation and drop nulls left by extractors."""
    cleaned = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return _HYPHEN_BREAK.sub("", cleaned)
