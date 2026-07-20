"""Workspace v2 wire-contract tests."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.task.schema import (
    ActionId,
    Artifact,
    Attachment,
    HistoryMessage,
    WorkspaceRequest,
    WorkspaceResponse,
)


REQUEST_ADAPTER = TypeAdapter(WorkspaceRequest)


def _artifact_id() -> UUID:
    """Create an Artifact identifier for one independently valid state."""

    return uuid4()


def _attachment(
    artifact_id: UUID,
    artifact_type: str = "cover_letter",
    *,
    attachment_id: UUID | None = None,
) -> dict[str, object]:
    """Build a valid version-one Attachment payload."""

    return {
        "id": attachment_id or uuid4(),
        "artifact_id": artifact_id,
        "version": 1,
        "type": artifact_type,
        "title": "Cover Letter" if artifact_type == "cover_letter" else "CV",
        "content": "Dear Hiring Manager" if artifact_type == "cover_letter" else "https://example.com/cv.pdf",
    }


def _artifacts(*, cover_letter: dict[str, object] | None = None) -> dict[str, object | None]:
    """Build the fixed-key Artifact map required by Workspace v2."""

    return {"cv": None, "cover_letter": cover_letter}


def _request_payload(**overrides: object) -> dict[str, object]:
    """Build a minimum valid user-message Workspace request payload."""

    payload: dict[str, object] = {
        "trigger": "user_message",
        "url": "https://example.com/jobs/1",
        "resourceUrl": "https://example.com/jobs/1",
        "actionId": "ask_more",
        "histories": [],
        "artifacts": _artifacts(),
        "message": "What should I highlight?",
    }
    payload.update(overrides)
    return payload


def test_workspace_request_is_discriminated_by_trigger() -> None:
    """Accept both trigger variants while preserving their typed contracts."""

    user_request = REQUEST_ADAPTER.validate_python(_request_payload())
    action_payload = _request_payload(trigger="quick_insight_action")
    action_payload.pop("message")
    action_request = REQUEST_ADAPTER.validate_python(action_payload)

    assert user_request.trigger == "user_message"
    assert action_request.trigger == "quick_insight_action"


def test_user_message_requires_message_and_reserves_one_history_slot() -> None:
    """Require user text and limit its incoming state to nine histories."""

    with pytest.raises(ValidationError, match="message"):
        REQUEST_ADAPTER.validate_python(_request_payload(message=""))
    with pytest.raises(ValidationError, match="histories"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(histories=[{"role": "user", "content": str(index)} for index in range(10)])
        )

    request = REQUEST_ADAPTER.validate_python(
        _request_payload(histories=[{"role": "user", "content": str(index)} for index in range(9)])
    )

    assert len(request.histories) == 9


def test_quick_insight_action_forbids_message_and_allows_ten_histories() -> None:
    """Allow the deterministic Action trigger to carry the full ten-message state."""

    payload = _request_payload(
        trigger="quick_insight_action",
        histories=[{"role": "user", "content": str(index)} for index in range(10)],
    )
    payload.pop("message")
    request = REQUEST_ADAPTER.validate_python(payload)

    assert len(request.histories) == 10
    with pytest.raises(ValidationError, match="message"):
        REQUEST_ADAPTER.validate_python(_request_payload(trigger="quick_insight_action", message="not allowed"))


def test_history_messages_have_identity_utc_time_and_attachment_rules() -> None:
    """Require complete messages and permit at most one Assistant attachment."""

    artifact_id = _artifact_id()
    assistant = HistoryMessage(
        role="assistant",
        content="Generated a cover letter.",
        action_id=ActionId.WRITE_COVER_LETTER,
        attachments=[_attachment(artifact_id)],
    )

    assert assistant.id
    assert assistant.created_at.tzinfo == timezone.utc
    assert len(assistant.attachments) == 1
    with pytest.raises(ValidationError, match="attachments"):
        HistoryMessage(role="user", content="Question", attachments=[_attachment(artifact_id)])
    with pytest.raises(ValidationError, match="attachments"):
        HistoryMessage(
            role="assistant",
            content="Two files",
            attachments=[_attachment(artifact_id), _attachment(_artifact_id())],
        )


def test_artifacts_require_exact_fixed_keys_and_valid_attachment_content() -> None:
    """Reject malformed Artifact maps and enforce each Attachment content contract."""

    with pytest.raises(ValidationError, match="cv"):
        REQUEST_ADAPTER.validate_python(_request_payload(artifacts={"cv": None}))
    with pytest.raises(ValidationError, match="extra"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(artifacts={"cv": None, "cover_letter": None, "other": None})
        )

    artifact_id = _artifact_id()
    with pytest.raises(ValidationError, match="content"):
        Attachment.model_validate({**_attachment(artifact_id, "cv"), "content": "relative/cv.pdf"})
    assert Attachment.model_validate(_attachment(artifact_id, "cover_letter")).content == "Dear Hiring Manager"


def test_workspace_state_enforces_identity_type_and_latest_attachment_invariants() -> None:
    """Keep message, Attachment and Artifact snapshots internally consistent."""

    artifact_id = _artifact_id()
    attachment = _attachment(artifact_id)
    artifact = {
        "id": artifact_id,
        "type": "cover_letter",
        "version": 1,
        "title": "Cover Letter",
        "draft": "Dear Hiring Manager",
        "attachment": attachment,
    }
    valid_payload = _request_payload(
        histories=[{"role": "assistant", "content": "Created it", "attachments": [attachment]}],
        artifacts=_artifacts(cover_letter=artifact),
    )

    assert REQUEST_ADAPTER.validate_python(valid_payload).artifacts.cover_letter is not None
    with pytest.raises(ValidationError, match="message IDs"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(
                histories=[
                    {"id": "00000000-0000-0000-0000-000000000001", "role": "user", "content": "one"},
                    {"id": "00000000-0000-0000-0000-000000000001", "role": "assistant", "content": "two"},
                ]
            )
        )
    with pytest.raises(ValidationError, match="Artifact type"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(artifacts=_artifacts(cover_letter={**artifact, "type": "cv"}))
        )
    with pytest.raises(ValidationError, match="latest Attachment"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(artifacts=_artifacts(cover_letter={**artifact, "attachment": _attachment(artifact_id)}))
        )


def test_workspace_limits_and_extra_fields_are_rejected() -> None:
    """Preserve text, title, version and legacy-field rejection boundaries."""

    artifact_id = _artifact_id()
    with pytest.raises(ValidationError, match="content"):
        HistoryMessage(role="user", content="x" * 10_001)
    with pytest.raises(ValidationError, match="title"):
        Attachment.model_validate({**_attachment(artifact_id), "title": "x" * 501})
    with pytest.raises(ValidationError, match="version"):
        Artifact.model_validate(
            {
                "id": artifact_id,
                "type": "cover_letter",
                "version": 0,
                "title": "Cover Letter",
                "draft": "draft",
                "attachment": _attachment(artifact_id),
            }
        )
    with pytest.raises(ValidationError, match="currentDocument"):
        REQUEST_ADAPTER.validate_python(_request_payload(currentDocument={}))


def test_workspace_response_is_markdown_only_full_state() -> None:
    """Return protocol-tagged full state without v1 document rendering fields."""

    response = WorkspaceResponse(
        resource_url="https://example.com/jobs/1",
        selected_action_id="ask_more",
        result_type="reply",
        histories=[],
        artifacts=_artifacts(),
    )

    dumped = response.model_dump()
    assert response.protocol_version == 2
    assert response.result_type == "reply"
    assert dumped["artifacts"] == {"cv": None, "cover_letter": None}
    assert not {"document", "html", "sections"}.intersection(dumped)
    with pytest.raises(ValidationError, match="result_type"):
        WorkspaceResponse(
            resource_url="https://example.com/jobs/1",
            selected_action_id="ask_more",
            histories=[],
            artifacts=_artifacts(),
        )
