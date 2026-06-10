from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# Built-in OpenAI-backed agents. "claude-code"/"codex" are reserved for future
# external adapters and are not implemented yet.
AgentName = Literal["summary_page", "job_match", "claude-code", "codex", "openclaw"]


class TaskCreate(BaseModel):
    """Incoming task from the browser extension.

    The extension posts a flat, camelCase payload
    (``{url, title, selectedText, pageText}``). We accept those keys via aliases
    while exposing snake_case attributes to the rest of the gateway.
    """

    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: str = ""
    selected_text: str = Field("", alias="selectedText")
    page_text: str = Field("", alias="pageText")
    intent: str = "Summarize this page."
    agent: AgentName = "summary_page"


class TaskRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["created", "completed", "failed"] = "created"
    request: TaskCreate
    prompt: str
    result: str = ""
    result_html: str = ""
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
