"""Shared fixtures.

Helpers live here rather than in an importable `tests.*` module: some
environments ship their own top-level `tests` package, which shadows this
directory on sys.path.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

MakePdf = Callable[[list[list[str]]], bytes]


@pytest.fixture
def make_pdf() -> MakePdf:
    """Build a minimal PDF. One list of lines per page, Helvetica, one Tj each."""
    return _make_pdf


def _make_pdf(pages: list[list[str]]) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        commands = ["BT", "/F1 12 Tf", "72 740 Td"]
        for index, line in enumerate(lines):
            if index:
                commands.append("0 -18 Td")
            commands.append(f"({_escape(line)}) Tj")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
