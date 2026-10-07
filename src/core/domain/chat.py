"""Chat blocks and SSE payloads. Mirrored by web/src/lib/types.ts."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from core.domain.models import Citation, SourceKind


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    content: str


class ToolBlock(BaseModel):
    type: Literal["tool"] = "tool"
    tool: str
    status: Literal["running", "done"]
    summary: str


class CitationsBlock(BaseModel):
    type: Literal["citations"] = "citations"
    items: list[Citation]


class ActionBlock(BaseModel):
    type: Literal["action"] = "action"
    action_id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class ErrorBlock(BaseModel):
    type: Literal["error"] = "error"
    message: str


class PendingAction(BaseModel):
    action_id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    question: str = Field(min_length=1)
    sources: list[SourceKind] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    # The paper the previous turn was about. Empty on the first question.
    focus_doc_id: str | None = None
    # The user message before this one, so "look for it on page 27" keeps its subject.
    prior_question: str | None = None


class StartEvent(BaseModel):
    message_id: str


class ToolEvent(BaseModel):
    tool: str
    status: Literal["running", "done"]
    hits: int | None = None


class DeltaEvent(BaseModel):
    text: str


class CitationEvent(BaseModel):
    n: int
    kind: SourceKind
    doc_id: str
    title: str
    uri: str
    locator: dict[str, Any] = Field(default_factory=dict)
    snippet: str = ""


class ActionEvent(BaseModel):
    action_id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class DoneEvent(BaseModel):
    latency_ms: int


class ErrorEvent(BaseModel):
    message: str
