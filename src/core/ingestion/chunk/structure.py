"""Pack a parsed document into chunks that keep their place in the paper.

Section boundaries win over size. A chunk never spans Methods into
Results, and a heading is carried into the chunks beneath it so a
retrieved fragment still says what part of the paper it came from. Size
is a band, not a rule: blocks accumulate until the target is reached,
and only a single block longer than the maximum is cut, on a sentence
boundary, with overlap.

Chunk ids are derived from the document, the chunking version, the
ordinal and the text itself. Re-running the same settings over an
unchanged file reproduces the same ids, so indexing is idempotent;
changing the settings changes the version and therefore every id, which
is what makes a re-index visible rather than silently partial.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from core.domain.models import BBox, Chunk
from core.ingestion.chunk.tokens import budget_chars, estimate_tokens
from core.ingestion.parse.base import LayoutBlock, PageText

DEFAULT_TARGET_TOKENS = 500
DEFAULT_MAX_TOKENS = 800
DEFAULT_MIN_TOKENS = 120
DEFAULT_OVERLAP_TOKENS = 80

_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_SECTION_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abstract", re.compile(r"^abstract\b", re.I)),
    ("introduction", re.compile(r"^(1\s+)?introduction\b", re.I)),
    ("background", re.compile(r"^(related work|background|preliminaries)\b", re.I)),
    ("methods", re.compile(r"^(method|methods|methodology|approach|model|design)\b", re.I)),
    ("results", re.compile(r"^(result|results|evaluation|experiments?|findings)\b", re.I)),
    ("discussion", re.compile(r"^(discussion|analysis|ablation)\b", re.I)),
    ("conclusion", re.compile(r"^(conclusion|conclusions|future work|summary)\b", re.I)),
    ("references", re.compile(r"^(references|bibliography)\b", re.I)),
    ("appendix", re.compile(r"^(appendix|supplementary)\b", re.I)),
    ("acknowledgements", re.compile(r"^acknowledge?ments?\b", re.I)),
)
_KNOWN_HEADING = re.compile(
    r"^(abstract|introduction|related work|background|method|methods|approach|"
    r"experiments?|results?|discussion|conclusion|conclusions|references|"
    r"acknowledgements?|acknowledgments?|appendix)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def chunk_document(
    doc_id: str,
    blocks: Sequence[LayoutBlock],
    *,
    chunking_version: str,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Build ordered, section-aware chunks with page and box provenance."""
    if target_tokens < 50:
        raise ValueError("target_tokens must be at least 50")
    if max_tokens < target_tokens:
        raise ValueError("max_tokens must be at least target_tokens")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be smaller than target_tokens")

    chunks: list[Chunk] = []
    bucket: list[LayoutBlock] = []
    heading_stack: list[tuple[int, str]] = []
    cursor = 0

    def section_path() -> str | None:
        return " > ".join(title for _, title in heading_stack) or None

    def flush() -> None:
        nonlocal cursor
        if not bucket:
            return
        path = section_path()
        body = "\n\n".join(block.text for block in bucket)
        pieces = _split_oversized(body, max_tokens, overlap_tokens)
        boxes = _merge_boxes(box for block in bucket for box in block.bboxes)
        page_start = min(block.page for block in bucket)
        page_end = max(block.page_end for block in bucket)
        bucket.clear()
        for piece in pieces:
            text = f"{path}\n\n{piece}" if path else piece
            start = cursor
            cursor += len(piece)
            chunks.append(
                _build(
                    doc_id=doc_id,
                    ord=len(chunks),
                    text=text,
                    chunking_version=chunking_version,
                    page_start=page_start,
                    page_end=page_end,
                    section_path=path,
                    section_kind=_section_kind(heading_stack),
                    bboxes=boxes,
                    char_start=start,
                    char_end=cursor,
                )
            )

    for block in blocks:
        if block.kind == "heading":
            flush()  # a section boundary always closes the chunk
            level, title = _heading_level(block.text)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            continue
        pending = estimate_tokens(block.text)
        held = estimate_tokens("\n\n".join(item.text for item in bucket))
        if bucket and held + pending > target_tokens and held >= min_tokens:
            flush()
        bucket.append(block)
    flush()
    return chunks


def chunk_pages(
    doc_id: str,
    pages: Sequence[PageText],
    *,
    chunking_version: str = "v2-pages",
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a parser that gave no layout: page text only, no boxes."""
    return chunk_document(
        doc_id,
        blocks_from_pages(pages),
        chunking_version=chunking_version,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        overlap_tokens=overlap_tokens,
    )


def is_heading(text: str) -> bool:
    line = " ".join(text.split())
    if not line or len(line) > 90 or "\n" in text.strip():
        return False
    if line.endswith((".", ",", ";")):
        return False
    if _KNOWN_HEADING.match(line) or _NUMBERED_HEADING.match(line):
        return True
    letters = [char for char in line if char.isalpha()]
    return bool(letters) and 3 <= len(line) <= 60 and all(char.isupper() for char in letters)


def _build(
    *,
    doc_id: str,
    ord: int,
    text: str,
    chunking_version: str,
    page_start: int,
    page_end: int,
    section_path: str | None,
    section_kind: str | None,
    bboxes: list[BBox],
    char_start: int,
    char_end: int,
) -> Chunk:
    return Chunk(
        id=chunk_id(doc_id, chunking_version, ord, text),
        doc_id=doc_id,
        ord=ord,
        text=text,
        token_count=estimate_tokens(text),
        page_start=page_start,
        page_end=page_end,
        section_path=section_path,
        section_kind=section_kind,
        bboxes=bboxes,
        char_start=char_start,
        char_end=char_end,
    )


def chunk_id(doc_id: str, chunking_version: str, ord: int, text: str) -> str:
    """Stable and content-addressed: same input, same id, every run."""
    seed = f"{doc_id}\x00{chunking_version}\x00{ord}\x00{text}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _heading_level(text: str) -> tuple[int, str]:
    match = _NUMBERED_HEADING.match(text.strip())
    if match is None:
        return 1, " ".join(text.split())
    return len(match.group(1).split(".")), " ".join(text.split())


def _section_kind(stack: Sequence[tuple[int, str]]) -> str | None:
    for _, title in stack:
        for kind, pattern in _SECTION_KINDS:
            if pattern.match(_strip_number(title)):
                return kind
    return None


def _strip_number(title: str) -> str:
    match = _NUMBERED_HEADING.match(title)
    return match.group(2) if match else title


def _split_oversized(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Only a block that cannot fit is cut, and then on a sentence boundary."""
    body = text.strip()
    if not body or estimate_tokens(body) <= max_tokens:
        return [body] if body else []
    limit = budget_chars(max_tokens)
    overlap = budget_chars(overlap_tokens)
    sentences = [part for part in _SENTENCE_END.split(body) if part.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > limit:
            pieces.append(current)
            current = f"{_tail(current, overlap)} {sentence}".strip()
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [piece for piece in (part.strip() for part in pieces) if piece]


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    window = text[-overlap:]
    space = window.find(" ")
    return window[space + 1 :] if space != -1 else window


def _merge_boxes(boxes: Iterable[BBox]) -> list[BBox]:
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


def blocks_from_pages(pages: Sequence[PageText]) -> list[LayoutBlock]:
    """Recover paragraph structure from flat page text, without geometry."""
    blocks: list[LayoutBlock] = []
    for page in pages:
        paragraph: list[str] = []

        def flush(page_number: int = 0) -> None:
            text = " ".join(paragraph).strip()
            paragraph.clear()
            if text:
                blocks.append(
                    LayoutBlock(
                        kind="paragraph", text=text, page=page_number, page_end=page_number
                    )
                )

        for raw_line in page.text.split("\n"):
            line = " ".join(raw_line.split())
            if not line:
                flush(page.page)
                continue
            if is_heading(line):
                flush(page.page)
                blocks.append(
                    LayoutBlock(kind="heading", text=line, page=page.page, page_end=page.page)
                )
                continue
            paragraph.append(line)
        flush(page.page)
    return _merge_page_breaks(blocks)


def _merge_page_breaks(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    if not blocks:
        return []
    merged = [blocks[0]]
    for block in blocks[1:]:
        previous = merged[-1]
        continues = (
            previous.kind == "paragraph"
            and block.kind == "paragraph"
            and block.page == previous.page_end + 1
            and re.search(r"[.!?…][\"')\]]*$", previous.text) is None
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
        )
    return merged
