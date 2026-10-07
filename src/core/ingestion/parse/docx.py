"""Word text extraction.

python-docx reads paragraphs, headings, lists, and tables. It does not
lay out pages, so every block shares page 1 and leaves boxes empty.
Chunking still sees headings and paragraphs. The viewer gets `preview`,
where a table stays a grid and a run of list items stays a list.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.domain.errors import ParseError
from core.ingestion.parse.base import LayoutBlock, PageText, ParsedDocument, PreviewBlock


class DocxParser:
    format = "docx"

    def parse(self, content: bytes) -> ParsedDocument:
        if not content:
            raise ParseError("Word document is empty")
        try:
            document = DocxDocument(BytesIO(content))
            layout, preview = _read(document)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError("Could not read Word document") from exc
        if not layout:
            raise ParseError("Word document has no text")
        text = "\n\n".join(block.text for block in layout)
        return ParsedDocument(
            pages=[PageText(page=1, text=text)],
            blocks=layout,
            preview=preview,
        )


def _read(document: DocxDocument) -> tuple[list[LayoutBlock], list[PreviewBlock]]:
    layout: list[LayoutBlock] = []
    preview: list[PreviewBlock] = []
    items: list[str] = []
    ordered = False

    def flush_list() -> None:
        nonlocal ordered
        if items:
            preview.append(PreviewBlock(kind="list", ordered=ordered, items=list(items)))
            items.clear()
        ordered = False

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = " ".join(paragraph.text.split())
            if not text:
                flush_list()
                continue
            name = _style_name(paragraph)
            if _is_heading(name):
                flush_list()
                layout.append(LayoutBlock(kind="heading", text=text, page=1, page_end=1))
                preview.append(PreviewBlock(kind="heading", text=text, level=_heading_level(name)))
                continue
            layout.append(LayoutBlock(kind="paragraph", text=text, page=1, page_end=1))
            if _is_list(paragraph, name):
                item_ordered = _is_ordered(name)
                if items and item_ordered != ordered:
                    flush_list()
                ordered = item_ordered
                items.append(text)
                continue
            flush_list()
            preview.append(PreviewBlock(kind="paragraph", text=text))
            continue
        if child.tag == qn("w:tbl"):
            flush_list()
            rows = _table_rows(Table(child, document))
            for cells in rows:
                layout.append(
                    LayoutBlock(kind="paragraph", text=" | ".join(cells), page=1, page_end=1)
                )
            if rows:
                preview.append(PreviewBlock(kind="table", rows=rows))
    flush_list()
    return layout, preview


def _style_name(paragraph: Paragraph) -> str:
    style = paragraph.style
    return style.name if style is not None else ""


def _is_heading(name: str) -> bool:
    return name in {"Title", "Subtitle"} or name.startswith("Heading")


def _heading_level(name: str) -> int:
    if name == "Title":
        return 1
    if name == "Subtitle":
        return 2
    digits = "".join(char for char in name if char.isdigit())
    if digits:
        return max(1, min(int(digits), 6))
    return 1


def _is_list(paragraph: Paragraph, name: str) -> bool:
    if name.startswith("List"):
        return True
    properties = paragraph._element.pPr
    return properties is not None and properties.numPr is not None


def _is_ordered(name: str) -> bool:
    return "Number" in name


def _table_rows(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if text and (not cells or cells[-1] != text):
                cells.append(text)
        if cells:
            rows.append(cells)
    return rows
