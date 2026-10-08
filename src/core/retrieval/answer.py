"""Turn retrieved passages into a grounded answer.

The prompt gives the model numbered passages and asks it to cite them.
Citations are emitted from the retrieval result rather than parsed out
of the model's prose: a hallucinated [7] can then point at nothing,
while every citation the reader sees is a real chunk with a real page.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from core.domain.models import Chunk, Citation
from core.llm.ollama import OllamaClient
from core.retrieval.hybrid import Retrieved
from core.retrieval.phrase import anchors
from core.store import IndexedDocument

SYSTEM_PROMPT = """You answer questions about the user's own library of papers and notes.

Rules:
- Use only the numbered passages provided. Do not add outside knowledge.
- Cite with bracketed numbers like [1] or [2][3] right after the claim they support.
- If the passages do not answer the question, say so plainly and name what is missing.
- Prefer the paper's own terms.
- Answer in the language the question was asked in.
- Be concise: lead with the conclusion, then support it. Do not restate the
  question or quote a passage at length.
- When the question asks for a specific value, state that value from the
  passage. Do not replace it with a range of nearby values.
- A paper record under a passage title lists authors, year, venue, and DOI
  when they are known. Use that record for those facts."""


def build_messages(
    question: str,
    hits: Sequence[Retrieved],
    documents: dict[str, IndexedDocument],
    *,
    prior_question: str | None = None,
) -> list[dict[str, str]]:
    passages = []
    introduced: set[str] = set()
    for number, hit in enumerate(hits, start=1):
        document = documents.get(hit.chunk.doc_id)
        title = document.title if document else hit.chunk.doc_id
        where = _where(hit)
        record = ""
        if document is not None and hit.chunk.doc_id not in introduced:
            introduced.add(hit.chunk.doc_id)
            record = _record(document)
        passages.append(f"[{number}] {title}{where}{record}\n{hit.chunk.text}")
    body = "\n\n".join(passages) if passages else "(no passages were found)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Passages:\n\n{body}\n\nQuestion: {_asked(question, prior_question)}",
        },
    ]


def citations_for(
    hits: Sequence[Retrieved],
    documents: dict[str, IndexedDocument],
) -> list[Citation]:
    found: list[Citation] = []
    for number, hit in enumerate(hits, start=1):
        document = documents.get(hit.chunk.doc_id)
        found.append(
            Citation(
                n=number,
                kind=_kind(hit.chunk.doc_id, document),
                doc_id=hit.chunk.doc_id,
                title=document.title if document else hit.chunk.doc_id,
                uri=document.uri if document else "",
                locator=hit.chunk.locator,
                snippet=_snippet(hit.chunk.text),
            )
        )
    return found


async def stream_answer(
    client: OllamaClient,
    question: str,
    hits: Sequence[Retrieved],
    documents: dict[str, IndexedDocument],
    *,
    prior_question: str | None = None,
) -> AsyncIterator[str]:
    messages = build_messages(question, hits, documents, prior_question=prior_question)
    async for piece in client.stream_chat(messages):
        yield piece


def carried_prior(question: str, prior: str | None) -> str | None:
    """The earlier question, when this turn only points back at it.

    """
    earlier = (prior or "").strip()
    if not earlier or earlier == question.strip():
        return None
    if anchors(question):
        return None
    return earlier


def _asked(question: str, prior_question: str | None) -> str:
    """A follow-up such as "look on page 27" still carries the earlier question."""
    earlier = carried_prior(question, prior_question)
    if not earlier:
        return question
    return f"{earlier}\nFollow-up: {question}"


def citation_for_document(
    document: IndexedDocument, *, snippet: str, chunk: Chunk | None = None
) -> Citation:
    """A citation for the paper itself, used when the answer is its record."""
    return Citation(
        n=1,
        kind=_kind(document.id, document),
        doc_id=document.id,
        title=document.title,
        uri=document.uri,
        locator=chunk.locator if chunk is not None else {"page": 1},
        snippet=snippet,
    )


def _record(document: IndexedDocument) -> str:
    lines: list[str] = []
    if document.authors:
        lines.append("Authors: " + ", ".join(document.authors))
    if document.year:
        lines.append(f"Year: {document.year}")
    if document.venue:
        lines.append(f"Venue: {document.venue}")
    if document.doi:
        lines.append(f"DOI: {document.doi}")
    if not lines:
        return ""
    return "\n" + "\n".join(lines)


def _where(hit: Retrieved) -> str:
    parts = []
    if hit.chunk.section_path:
        parts.append(hit.chunk.section_path)
    if hit.chunk.page_start == hit.chunk.page_end:
        parts.append(f"page {hit.chunk.page_start}")
    else:
        parts.append(f"pages {hit.chunk.page_start}-{hit.chunk.page_end}")
    return f" ({', '.join(parts)})"


def _kind(doc_id: str, document: IndexedDocument | None) -> str:
    if document is not None:
        return document.source
    head = doc_id.split(":", 1)[0]
    return head or "file"


def _snippet(text: str, limit: int = 800) -> str:
    body = " ".join(text.split())
    if len(body) <= limit:
        return body
    return body[:limit].rsplit(" ", 1)[0] + "…"
