"""Register built-in parsers. Importing this package makes PDF and Word available."""

from core.ingestion.parse.base import LayoutBlock, PageText, ParsedDocument, Parser
from core.ingestion.parse.docx import DocxParser
from core.ingestion.parse.pdf import PdfParser, looks_like_heading, normalize_page_text
from core.ingestion.parse.registry import get_parser, register_parser, registered_formats

# Blocks and boxes come from here, so a change in extraction changes the
# chunks even when the chunk settings are untouched. Bump it when parsing
# behaviour changes, or a re-index will be skipped as already current.
PARSER_VERSION = "pymupdf-4"

register_parser(PdfParser())
register_parser(DocxParser())

__all__ = [
    "PARSER_VERSION",
    "DocxParser",
    "LayoutBlock",
    "PageText",
    "ParsedDocument",
    "Parser",
    "PdfParser",
    "get_parser",
    "looks_like_heading",
    "normalize_page_text",
    "register_parser",
    "registered_formats",
]
