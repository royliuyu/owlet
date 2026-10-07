"""Token estimation.

Qwen's tokenizer is not available without pulling transformers, and the
chunker only needs to be right enough to keep chunks inside a band. CJK
runs about one token per character; Latin script about one per four.
Counts are stored per chunk, so swapping this for a real tokenizer later
is a re-index, not a schema change.
"""

from __future__ import annotations

import re

_CJK = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    latin = len(text) - cjk
    return cjk + -(-latin // 4)


def budget_chars(tokens: int) -> int:
    """Rough inverse, for slicing inside an oversized paragraph."""
    return max(1, tokens * 4)
