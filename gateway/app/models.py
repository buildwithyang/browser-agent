from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# "simple" is the built-in OpenAI-backed agent. The others are reserved for
# future external adapters and are not implemented in the MVP.
AgentName = Literal["simple", "claude-code", "codex", "openclaw"]


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
    intent: str = "Analyze this page and propose next steps."
    agent: AgentName = "simple"


class TaskRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["created", "completed", "failed"] = "created"
    request: TaskCreate
    prompt: str
    result: str = ""
    error: str = ""
