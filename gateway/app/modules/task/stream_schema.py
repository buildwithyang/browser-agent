"""Strict protocol-v3 NDJSON event contracts for Workspace streaming."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.task.schema import (
    DOCUMENT_TEXT_MAX_CHARS,
    TITLE_MAX_CHARS,
    ArtifactType,
    WorkspaceResponse,
)


class WorkspaceStreamStage(StrEnum):
    """Stable progress stages exposed by a Workspace event stream."""

    ROUTING = "routing"
    GENERATING_REPLY = "generating_reply"
    GENERATING_ARTIFACT = "generating_artifact"
    FINALIZING = "finalizing"


class WorkspaceStreamEventBase(BaseModel):
    """Shared correlation and ordering fields for every Workspace stream event."""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    sequence: int = Field(ge=0)


class WorkspaceStartedEvent(WorkspaceStreamEventBase):
    """The first event emitted after Workspace stream preparation succeeds."""

    type: Literal["started"] = "started"
    created_at: datetime


class WorkspaceStatusEvent(WorkspaceStreamEventBase):
    """One non-terminal progress update for the active Workspace operation."""

    type: Literal["status"] = "status"
    stage: WorkspaceStreamStage
    artifact_type: ArtifactType | None = None

    @model_validator(mode="after")
    def validate_artifact_stage(self) -> "WorkspaceStatusEvent":
        """Allow artifact metadata only for artifact-generation progress."""

        has_artifact_type = self.artifact_type is not None
        is_artifact_stage = self.stage is WorkspaceStreamStage.GENERATING_ARTIFACT
        if has_artifact_type != is_artifact_stage:
            raise ValueError("artifact_type is required only for generating_artifact")
        return self


class WorkspaceDeltaEvent(WorkspaceStreamEventBase):
    """One non-empty provider text fragment for an ordinary reply."""

    type: Literal["delta"] = "delta"
    text: str = Field(min_length=1, max_length=DOCUMENT_TEXT_MAX_CHARS)


class WorkspaceCompletedEvent(WorkspaceStreamEventBase):
    """The sole successful terminal event with the canonical final state."""

    type: Literal["completed"] = "completed"
    response: WorkspaceResponse


class WorkspaceFailedEvent(WorkspaceStreamEventBase):
    """The sole failed terminal event emitted after streaming starts."""

    type: Literal["failed"] = "failed"
    code: Literal[
        "model_error",
        "invalid_model_output",
        "stream_interrupted",
        "internal_error",
    ]
    message: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    recoverable: bool


WorkspaceStreamEvent = Annotated[
    WorkspaceStartedEvent
    | WorkspaceStatusEvent
    | WorkspaceDeltaEvent
    | WorkspaceCompletedEvent
    | WorkspaceFailedEvent,
    Field(discriminator="type"),
]


def encode_stream_event(event: WorkspaceStreamEvent) -> bytes:
    """Serialize exactly one UTF-8 NDJSON event line."""

    return (event.model_dump_json() + "\n").encode("utf-8")
