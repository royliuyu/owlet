"""Which lines count as section headings.

Every case here is a line taken from the papers in the test library. The
section path ends up prepended to chunk text and shown under a citation,
so a paragraph promoted to a heading is visible to the reader.
"""

import pytest

from core.ingestion.parse import looks_like_heading

# These papers set body text at 10.1 and headings at 10.0, which is why a
# heading cannot be required to be larger than the body.
BODY = 10.1

HEADINGS = [
    ("1. Introduction", 10.0),
    ("2.1. Solo Inference", 10.0),
    ("5.4.1. mAP", 10.0),
    ("5.4. mAP and Overhead of L-Filter", 10.0),
    ("4.1.1. Dataset 1", 10.0),
    ("5. CNN Models, Transformer Models, Datasets, Performance Metrics", 9.9),
    ("3.1. An Overview of the Method", 10.0),
    ("References", 10.0),
    ("ACKNOWLEDGEMENT", 10.0),
    ("Corun: Concurrent Inference and Continuous Training at the", 17.9),
]

NOT_HEADINGS = [
    # Prose set a tenth of a point above the body, which a median-based
    # body size used to mistake for emphasis.
    ("The advances in ML and mobile/wearable technology, such as", 10.1),
    ("4. However, the normalized average inference latency increases", 9.9),
    ("EMA data. Predicting depression by analyzing both mobile EMA", 10.1),
    # A section word opening a paragraph is not a section heading.
    ("Acknowledgments: We appreciate anonymous reviwers for their", 9.1),
    ("Abstract—Real-time object detection is essential for AI-based", 9.0),
    # Reference entries and figure keys.
    ("25 February–1 March 2023; IEEE: Piscataway, NJ, USA", 9.0),
    ("Methods Psychiatr. Res. 2008, 17, 121–140 [CrossRef]", 9.0),
    ("1 stream", 8.5),
    ("Training job", 15.6),
    ("Optical flow analysis", 13.9),
    # Pseudocode and equations.
    ("1 K = 0 // solo training with no inference", 10.4),
    ("2 for K = 1; K ++ do", 10.4),
    ("9 return M", 10.0),
    # A table caption, not the Methods section.
    ("Model", 9.0),
    # Running heads and folios.
    ("14 of 19", 9.0),
]


@pytest.mark.parametrize(("text", "size"), HEADINGS)
def test_section_headings_are_recognised(text: str, size: float) -> None:
    assert looks_like_heading(text, size=size, body_size=BODY)


@pytest.mark.parametrize(("text", "size"), NOT_HEADINGS)
def test_body_text_is_not_promoted(text: str, size: float) -> None:
    assert not looks_like_heading(text, size=size, body_size=BODY)


def test_a_title_stands_out_by_size_alone() -> None:
    """With no number or section word left, size is the only evidence."""
    assert looks_like_heading("Pixel Motion Speed", size=23.9, body_size=BODY)
    assert not looks_like_heading("Pixel Motion Speed", size=10.1, body_size=BODY)
