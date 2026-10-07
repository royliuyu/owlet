"""PDF extraction, structural chunking, and chunk provenance."""

from collections.abc import Callable
from datetime import datetime, timezone

import pytest

from core.connectors.base import RawDocument
from core.domain.errors import ParseError
from core.ingestion.chunk import chunk_document, chunk_id, chunk_pages, estimate_tokens
from core.ingestion.parse import PdfParser, normalize_page_text, registered_formats
from core.ingestion.parse.base import LayoutBlock, PageText
from core.ingestion.preview import parse_to_chunks

MakePdf = Callable[[list[list[str]]], bytes]
VERSION = "test-v1"


def test_pdf_parser_keeps_each_page(make_pdf: MakePdf) -> None:
    content = make_pdf(
        [
            ["1 Introduction", "Attention is all you need."],
            ["2 Related Work", "Prior models were recurrent."],
        ]
    )
    parsed = PdfParser().parse(content)

    assert [page.page for page in parsed.pages] == [1, 2]
    assert "Introduction" in parsed.pages[0].text
    assert "Attention is all you need." in parsed.pages[0].text
    assert "Related Work" in parsed.pages[1].text
    assert "pdf" in registered_formats()


def test_pdf_parser_reports_where_text_sits(make_pdf: MakePdf) -> None:
    parsed = PdfParser().parse(make_pdf([["1 Introduction", "Attention is all you need."]]))

    assert parsed.blocks, "layout blocks are what citations highlight"
    boxes = [box for block in parsed.blocks for box in block.bboxes]
    assert boxes
    for box in boxes:
        assert box.page == 1
        assert 0.0 <= box.x0 <= box.x1 <= 1.0
        assert 0.0 <= box.y0 <= box.y1 <= 1.0


def test_pdf_parser_rejects_garbage() -> None:
    with pytest.raises(ParseError):
        PdfParser().parse(b"this is not a pdf")


def test_normalize_rejoins_hyphenated_line_breaks() -> None:
    assert normalize_page_text("self-\nattention") == "selfattention"


def test_chunks_record_section_and_merge_across_pages() -> None:
    pages = [
        PageText(page=1, text="1 Introduction\n\nAttention is all you need"),
        PageText(page=2, text="for sequences of any length."),
    ]
    chunks = chunk_pages("paper:lib/a.pdf", pages, chunking_version=VERSION)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.ord == 0
    assert chunk.page_start == 1
    assert chunk.page_end == 2
    assert chunk.section_path == "1 Introduction"
    assert chunk.section_kind == "introduction"
    assert chunk.token_count == estimate_tokens(chunk.text)
    assert "for sequences of any length." in chunk.text
    assert chunk.locator == {"page": 1, "page_end": 2, "section": "1 Introduction"}


def test_a_section_boundary_always_closes_a_chunk() -> None:
    blocks = [
        LayoutBlock(kind="heading", text="3 Methods", page=1, page_end=1),
        LayoutBlock(kind="paragraph", text="We trained on four GPUs.", page=1, page_end=1),
        LayoutBlock(kind="heading", text="4 Results", page=1, page_end=1),
        LayoutBlock(kind="paragraph", text="Accuracy rose by two points.", page=1, page_end=1),
    ]
    chunks = chunk_document("paper:lib/a.pdf", blocks, chunking_version=VERSION)

    assert len(chunks) == 2, "Methods must not bleed into Results"
    assert chunks[0].section_kind == "methods"
    assert chunks[1].section_kind == "results"
    assert "Accuracy" not in chunks[0].text


def test_subsections_build_a_path() -> None:
    blocks = [
        LayoutBlock(kind="heading", text="2 Related Work", page=1, page_end=1),
        LayoutBlock(kind="heading", text="2.1 Solo Inference", page=1, page_end=1),
        LayoutBlock(kind="paragraph", text="Serving systems target latency.", page=1, page_end=1),
    ]
    chunks = chunk_document("paper:lib/a.pdf", blocks, chunking_version=VERSION)

    assert chunks[0].section_path == "2 Related Work > 2.1 Solo Inference"
    assert chunks[0].section_kind == "background"


def test_long_paragraph_splits_with_overlap() -> None:
    sentence = "Self attention relates every token to every other token. "
    chunks = chunk_pages(
        "paper:lib/long.pdf",
        [PageText(page=3, text=sentence * 60)],
        chunking_version=VERSION,
        target_tokens=120,
        max_tokens=160,
        overlap_tokens=40,
    )

    assert len(chunks) > 1
    assert all(chunk.page_start == 3 for chunk in chunks)
    assert [chunk.ord for chunk in chunks[:2]] == [0, 1]
    tail = chunks[0].text.split()[-4:]
    assert " ".join(tail) in chunks[1].text


def test_chunk_ids_are_stable_and_version_scoped() -> None:
    pages = [PageText(page=1, text="Abstract\n\nA short summary of the paper.")]
    first = chunk_pages("paper:lib/a.pdf", pages, chunking_version=VERSION)
    again = chunk_pages("paper:lib/a.pdf", pages, chunking_version=VERSION)
    other = chunk_pages("paper:lib/a.pdf", pages, chunking_version="test-v2")

    assert [c.id for c in first] == [c.id for c in again], "re-indexing must be idempotent"
    assert [c.id for c in first] != [c.id for c in other], "a new layout is a new chunk"
    assert first[0].id == chunk_id("paper:lib/a.pdf", VERSION, 0, first[0].text)
    assert len(first[0].id) == 32


def test_parse_to_chunks_uses_the_pdf_parser(make_pdf: MakePdf) -> None:
    content = make_pdf([["Abstract", "A short summary of the paper."]])
    raw = RawDocument(
        source_id="lib/paper.pdf",
        source="paper",
        title="paper",
        uri="file:///paper.pdf",
        media_type="application/pdf",
        content=content,
        content_hash="abc",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        extra={"format": "pdf"},
    )

    chunks = parse_to_chunks(raw, chunking_version=VERSION)

    assert chunks
    assert chunks[0].doc_id == "paper:lib/paper.pdf"
    assert chunks[0].page_start == 1
    assert "short summary" in chunks[0].text
