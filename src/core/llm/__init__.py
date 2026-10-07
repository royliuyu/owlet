"""Embedding and chat models. Ollama by default, any OpenAI-ish host via base_url."""

from core.llm.ollama import EmbeddingClient, LLMUnavailableError, OllamaClient

__all__ = ["EmbeddingClient", "LLMUnavailableError", "OllamaClient"]
