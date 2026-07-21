"""Protocol-v4 NDJSON Workspace event schema tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.task.schema import Artifacts, WorkspaceRequest, WorkspaceResponse
from app.modules.task.stream_schema import (
    WorkspaceCompletedEvent,
    WorkspaceDeltaEvent,
    WorkspaceFailedEvent,
    WorkspaceStartedEvent,
    WorkspaceStatusEvent,
    WorkspaceStreamEvent,
    WorkspaceStreamStage,
    encode_stream_event,
)


STREAM_EVENT_ADAPTER = TypeAdapter(WorkspaceStreamEvent)


def workspace_payload() -> dict[str, object]:
    """Build one valid Workspace request except for the operation ID under test."""

    return {
        "url": "https://example.com/article",
        "resourceUrl": "https://example.com/article",
        "histories": [],
        "artifacts": {"cv": None, "cover_letter": None},
        "message": "What matters?",
    }


def test_workspace_request_requires_operation_id() -> None:
    """Require the Extension correlation UUID in every Workspace request."""

    payload = workspace_payload()
    with pytest.raises(ValidationError, match="operationId"):
        WorkspaceRequest.model_validate(payload)

    operation_id = uuid4()
    request = WorkspaceRequest.model_validate(
        {**payload, "operationId": str(operation_id)}
    )

    assert request.operation_id == operation_id


def test_delta_event_encodes_one_utf8_ndjson_line() -> None:
    """Encode exactly one complete UTF-8 JSON event followed by a newline."""

    operation_id = uuid4()
    event = WorkspaceDeltaEvent(
        operation_id=operation_id,
        sequence=2,
        text="这个岗",
    )
    encoded = encode_stream_event(event)

    assert encoded.endswith(b"\n")
    assert json.loads(encoded) == {
        "type": "delta",
        "operation_id": str(operation_id),
        "sequence": 2,
        "text": "这个岗",
    }


@pytest.mark.parametrize(
    ("event", "unknown_field"),
    [
        (WorkspaceStartedEvent, "created_at"),
        (WorkspaceStatusEvent, "stage"),
        (WorkspaceDeltaEvent, "text"),
        (WorkspaceCompletedEvent, "response"),
        (WorkspaceFailedEvent, "code"),
    ],
)
def test_stream_events_reject_unknown_fields(event: type[object], unknown_field: str) -> None:
    """Keep every wire event closed to silently ignored client fields."""

    operation_id = uuid4()
    payload: dict[str, object] = {
        "operation_id": operation_id,
        "sequence": 0,
        "unexpected": "rejected",
    }
    if event is WorkspaceStartedEvent:
        payload.update(type="started", created_at=datetime.now(timezone.utc))
    elif event is WorkspaceStatusEvent:
        payload.update(type="status", stage="routing")
    elif event is WorkspaceDeltaEvent:
        payload.update(type="delta", text="text")
    elif event is WorkspaceCompletedEvent:
        payload.update(
            type="completed",
            response=WorkspaceResponse(
                resource_url="https://example.com/article",
                result_type="reply",
                histories=[],
                artifacts=Artifacts(cv=None, cover_letter=None),
            ),
        )
    else:
        payload.update(type="failed", code="model_error", message="Failed", recoverable=True)

    with pytest.raises(ValidationError, match="unexpected"):
        event(**payload)  # type: ignore[operator]


@pytest.mark.parametrize("sequence", [-1, 0, 1])
def test_stream_event_sequence_is_non_negative(sequence: int) -> None:
    """Represent only non-negative sequence values for client monotonic checks."""

    payload = {
        "type": "delta",
        "operation_id": UUID("00000000-0000-0000-0000-000000000001"),
        "sequence": sequence,
        "text": "text",
    }
    if sequence < 0:
        with pytest.raises(ValidationError, match="sequence"):
            STREAM_EVENT_ADAPTER.validate_python(payload)
    else:
        assert STREAM_EVENT_ADAPTER.validate_python(payload).sequence == sequence


def test_status_event_allows_artifact_type_only_while_generating_artifact() -> None:
    """Bind Artifact progress metadata to the sole applicable stream stage."""

    operation_id = uuid4()
    event = WorkspaceStatusEvent(
        operation_id=operation_id,
        sequence=1,
        stage=WorkspaceStreamStage.GENERATING_ARTIFACT,
        artifact_type="cv",
    )

    assert event.artifact_type == "cv"
    with pytest.raises(ValidationError, match="artifact_type"):
        WorkspaceStatusEvent(
            operation_id=operation_id,
            sequence=2,
            stage=WorkspaceStreamStage.ROUTING,
            artifact_type="cv",
        )


def test_status_wire_omits_only_its_inapplicable_artifact_type() -> None:
    """Omit status-only null metadata without stripping canonical null Artifacts."""

    operation_id = uuid4()
    status = WorkspaceStatusEvent(
        operation_id=operation_id,
        sequence=1,
        stage=WorkspaceStreamStage.ROUTING,
    )
    completed = WorkspaceCompletedEvent(
        operation_id=operation_id,
        sequence=2,
        response=WorkspaceResponse(
            resource_url="https://example.com/article",
            result_type="reply",
            histories=[],
            artifacts=Artifacts(cv=None, cover_letter=None),
        ),
    )

    assert "artifact_type" not in json.loads(encode_stream_event(status))
    assert json.loads(encode_stream_event(completed))["response"]["artifacts"] == {
        "cv": None,
        "cover_letter": None,
    }


def test_completed_event_rejects_removed_selected_action_id() -> None:
    """Keep the terminal v4 response free of Action routing metadata."""

    with pytest.raises(ValidationError, match="selected_action_id"):
        STREAM_EVENT_ADAPTER.validate_python(
            {
                "type": "completed",
                "operation_id": str(uuid4()),
                "sequence": 1,
                "response": {
                    "resource_url": "https://example.com/article",
                    "selected_action_id": "analyze",
                    "result_type": "reply",
                    "histories": [],
                    "artifacts": {"cv": None, "cover_letter": None},
                },
            }
        )
