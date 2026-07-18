from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.modules.task.schema import (
    AgentName,
    IMAGE_TEXT_MAX_CHARS,
    PAGE_TEXT_MAX_CHARS,
    Recommendation,
    SELECTED_TEXT_MAX_CHARS,
)


class LegacyTaskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str
    title: str = ""
    selected_text: str = Field("", alias="selectedText", max_length=SELECTED_TEXT_MAX_CHARS)
    page_text: str = Field("", alias="pageText", max_length=PAGE_TEXT_MAX_CHARS)
    image_text: str = Field("", alias="imageText", max_length=IMAGE_TEXT_MAX_CHARS)
    sections: list[str] | None = None
    prior_result: str | None = Field(default=None, alias="priorResult", max_length=50_000)
    intent: str = "Summarize this page."
    agent: AgentName = AgentName.SUMMARY_PAGE
    lang: Literal["auto", "zh", "en"] = "auto"


class LegacySection(BaseModel):
    id: str
    title: str
    html: str
    copyable: bool = False
    collapsible: bool = True


class LegacyJobOverview(BaseModel):
    industry_business: str
    role_focus: str
    summary: str


class LegacyQuickInsight(BaseModel):
    type: Literal["job_match", "summary"]
    title: str
    summary_html: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None
    reason: str = ""
    job_overview: LegacyJobOverview | None = None
    top_strength: str = ""
    top_gap: str = ""


class LegacyAction(BaseModel):
    id: str
    label: str
    sections: list[str] = Field(default_factory=list)
    task_type: str = ""
    enabled: bool = True


class LegacyTaskResponse(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["created", "completed", "failed"] = "completed"
    request: LegacyTaskRequest
    input_chars: int = 0
    model: str = ""
    result: str = ""
    result_html: str = ""
    sections: list[LegacySection] = Field(default_factory=list)
    actions: list[LegacyAction] = Field(default_factory=list)
    insight: LegacyQuickInsight | None = None
    error: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
