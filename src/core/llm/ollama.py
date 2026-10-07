"""Ollama client for embeddings and streamed chat.

Embeddings are the index's dependency and chat is the answer's, but both
speak to the same host, so they share one client and one timeout. The
embedding model and its dimension are recorded alongside every vector:
swapping the model is a re-index, not a silent change.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

import httpx

from core.domain.errors import CoreError


class LLMUnavailableError(CoreError):
    """The model host could not be reached, or refused the request."""


class EmbeddingClient(Protocol):
    """What the index needs. Keeps ingestion off a concrete vendor."""

    model: str
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OllamaClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        embedding_model: str,
        embedding_dim: int,
        timeout: float = 180.0,
        num_ctx: int = 8192,
        embed_batch: int = 16,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._chat_model = model
        self.model = embedding_model
        self.dim = embedding_dim
        self._timeout = timeout
        self._num_ctx = num_ctx
        self._embed_batch = max(1, embed_batch)

    @property
    def chat_model(self) -> str:
        return self._chat_model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed in batches. Order of the result matches the input."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), self._embed_batch):
                batch = list(texts[start : start + self._embed_batch])
                payload = await self._post(
                    client, "/api/embed", {"model": self.model, "input": batch}
                )
                found = payload.get("embeddings")
                if not isinstance(found, list) or len(found) != len(batch):
                    raise LLMUnavailableError(
                        f"{self.model} returned {len(found or [])} vectors for "
                        f"{len(batch)} inputs"
                    )
                for vector in found:
                    if len(vector) != self.dim:
                        raise LLMUnavailableError(
                            f"{self.model} returned dimension {len(vector)}, "
                            f"but the index was built for {self.dim}. Re-index "
                            f"after changing the embedding model."
                        )
                    vectors.append([float(value) for value in vector])
        return vectors

    async def stream_chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Yield answer text as it arrives.

        Deliberately no "think" flag. A reasoning model asked not to think
        reasons anyway and Ollama puts that prose in `content`; left alone it
        separates reasoning into `thinking` and leaves `content` clean. We
        only read `content`, so omitting the flag is what strips the preamble.
        """
        body = {
            "model": self._chat_model,
            "messages": list(messages),
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": self._num_ctx},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                async with client.stream(
                    "POST", f"{self._base_url}/api/chat", json=body
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")
                        raise LLMUnavailableError(_explain(response.status_code, detail))
                    async for line in response.aiter_lines():
                        text = _delta(line)
                        if text:
                            yield text
            except httpx.HTTPError as exc:
                raise LLMUnavailableError(_unreachable(self._base_url)) from exc

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict[str, object]
    ) -> dict[str, object]:
        try:
            response = await client.post(f"{self._base_url}{path}", json=body)
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(_unreachable(self._base_url)) from exc
        if response.status_code >= 400:
            raise LLMUnavailableError(_explain(response.status_code, response.text))
        return response.json()


def _delta(line: str) -> str:
    if not line.strip():
        return ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _unreachable(base_url: str) -> str:
    return (
        f"Could not reach the model host at {base_url}. "
        "Start Ollama, or point OWLET_LLM__BASE_URL somewhere else."
    )


def _explain(status: int, detail: str) -> str:
    body = detail.strip()
    if status == 404 and "model" in body.lower():
        return f"{body} Pull it with `ollama pull <model>`."
    return f"The model host returned {status}: {body[:300]}"
