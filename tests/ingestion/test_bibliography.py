"""The first-page paper record, without re-chunking."""

import pymupdf

from core.ingestion.parse.bibliography import (
    authors_before_abstract,
    doi_from_text,
    read_bibliography,
    split_authors,
    venue_from_lines,
    year_from_lines,
)


def test_split_authors_keeps_hyphenated_names() -> None:
    names = split_authors("Yu Liu, Anurag Andhare, and Kyoung-Don Kang *")

    assert names == ["Yu Liu", "Anurag Andhare", "Kyoung-Don Kang"]


def test_a_title_line_is_not_a_byline() -> None:
    assert split_authors("Corun: Concurrent Inference and Continuous Training at the") == []


def test_authors_sit_between_the_title_and_the_abstract() -> None:
    lines = [
        ("AROD: Adaptive Resource-aware Object Detection", 24.0),
        ("for Vehicular Networks", 24.0),
        ("Yu Liu, Kyoung-Don Kang", 11.0),
        ("Department of Computer Science", 10.0),
        ("Abstract The detector adapts its model.", 11.0),
    ]

    assert authors_before_abstract(lines) == ["Yu Liu", "Kyoung-Don Kang"]


def test_venue_year_and_doi_from_the_first_page_lines() -> None:
    lines = [
        "2024 IEEE 100th Vehicular Technology Conference (VTC2024-Fall)",
        "Copyright ©2024 IEEE",
        "Sensors 2024, 24, 5262",
    ]

    assert "Conference" in venue_from_lines(lines)
    assert year_from_lines(lines) == 2024
    assert doi_from_text("https://doi.org/10.3390/s24165262.") == "10.3390/s24165262"


def test_a_generated_byline_is_read_when_metadata_is_empty() -> None:
    record = read_bibliography(
        _pdf(
            [
                ("AROD: Adaptive Detection", 18),
                ("Ada Lovelace, Alan Turing", 11),
                ("Abstract The method works.", 10),
            ]
        )
    )

    assert record["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert record["title"] == "AROD: Adaptive Detection"
    assert record["v"] == 1


def test_pdf_metadata_authors_win_over_the_page() -> None:
    record = read_bibliography(
        _pdf(
            [("Corun: Concurrent Inference", 18), ("Abstract The method works.", 11)],
            metadata={"author": "Yu Liu, Anurag Andhare, and Kyoung-Don Kang", "title": "Corun"},
        )
    )

    assert record["authors"] == ["Yu Liu", "Anurag Andhare", "Kyoung-Don Kang"]
    assert record["title"] == "Corun"


def _pdf(lines: list[tuple[str, float]], *, metadata: dict[str, str] | None = None) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    y = 72.0
    for text, size in lines:
        page.insert_text((72, y), text, fontsize=size, fontname="helv")
        y += size + 8
    if metadata:
        document.set_metadata(metadata)
    content = document.tobytes()
    document.close()
    return content
