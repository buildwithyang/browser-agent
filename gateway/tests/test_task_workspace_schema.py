"""Workspace v4 wire-contract tests."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.task.schema import (
    Artifact,
    Attachment,
    HistoryMessage,
    WorkspaceRequest,
    WorkspaceResponse,
    count_user_turns,
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
        "url": "https://example.com/jobs/1",
        "resourceUrl": "https://example.com/jobs/1",
        "histories": [],
        "artifacts": _artifacts(),
        "message": "What should I highlight?",
        "operationId": "00000000-0000-0000-0000-000000000001",
    }
    payload.update(overrides)
    return payload


def test_workspace_request_accepts_only_one_user_message_shape() -> None:
    request = WorkspaceRequest.model_validate(_request_payload(message="Analyze this role."))

    assert request.message == "Analyze this role."


def test_workspace_request_requires_message() -> None:
    """Require one non-empty user message for every Workspace transition."""

    with pytest.raises(ValidationError, match="message"):
        REQUEST_ADAPTER.validate_python(_request_payload(message=""))


@pytest.mark.parametrize(
    ("field", "value"),
    [("trigger", "user_message"), ("actionId", "analyze")],
)
def test_workspace_request_rejects_removed_action_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        WorkspaceRequest.model_validate({**_request_payload(), field: value})


def _paired_histories(turns: int) -> list[HistoryMessage]:
    """Build complete canonical user/Assistant pairs for turn-limit tests."""

    return [
        HistoryMessage(role=role, content=f"{role}-{turn}")
        for turn in range(turns)
        for role in ("user", "assistant")
    ]


def test_workspace_allows_tenth_user_turn_but_rejects_eleventh() -> None:
    nine_turns = _paired_histories(turns=9)
    assert count_user_turns(nine_turns) == 9
    assert WorkspaceRequest.model_validate(
        {**_request_payload(), "histories": [item.model_dump() for item in nine_turns]}
    )

    with pytest.raises(ValidationError, match="10 user turns"):
        WorkspaceRequest.model_validate(
            {
                **_request_payload(),
                "histories": [item.model_dump() for item in _paired_histories(turns=10)],
            }
        )


def _role_histories(*, users: int, assistants: int) -> list[HistoryMessage]:
    """Build a canonical-role history collection for migrated-state bounds."""

    return [
        *[HistoryMessage(role="user", content=f"user-{index}") for index in range(users)],
        *[
            HistoryMessage(role="assistant", content=f"assistant-{index}")
            for index in range(assistants)
        ],
    ]


def test_workspace_accepts_maximum_valid_migrated_request_state() -> None:
    """Reserve two response slots after nine v4 turns and eleven legacy replies."""

    histories = _role_histories(users=9, assistants=20)

    request = WorkspaceRequest.model_validate(
        {**_request_payload(), "histories": [item.model_dump() for item in histories]}
    )

    assert len(request.histories) == 29


@pytest.mark.parametrize(
    ("users", "assistants"),
    [(9, 21), (2, 1), (0, 31)],
)
def test_workspace_rejects_invalid_migrated_role_balance(
    users: int,
    assistants: int,
) -> None:
    """Reject surplus Assistants, missing replies, and Assistant-only capacity abuse."""

    histories = _role_histories(users=users, assistants=assistants)

    with pytest.raises(ValidationError, match="role balance"):
        WorkspaceRequest.model_validate(
            {
                **_request_payload(),
                "histories": [item.model_dump() for item in histories],
            }
        )


def test_history_messages_have_identity_utc_time_and_attachment_rules() -> None:
    """Require complete messages and permit at most one Assistant attachment."""

    artifact_id = _artifact_id()
    assistant = HistoryMessage(
        role="assistant",
        content="Generated a cover letter.",
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


def test_workspace_state_rejects_artifact_version_that_differs_from_latest_attachment() -> None:
    """Require the latest Artifact and its embedded Attachment to name one version."""

    artifact_id = _artifact_id()
    attachment = _attachment(artifact_id)
    artifact = {
        "id": artifact_id,
        "type": "cover_letter",
        "version": 2,
        "title": "Cover Letter",
        "draft": "Dear Hiring Manager",
        "attachment": attachment,
    }

    with pytest.raises(ValidationError, match="Artifact version must equal its Attachment version"):
        REQUEST_ADAPTER.validate_python(
            _request_payload(
                histories=[
                    {
                        "role": "assistant",
                        "content": "Created it",
                        "attachments": [attachment],
                    }
                ],
                artifacts=_artifacts(cover_letter=artifact),
            )
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


def test_history_and_response_reject_removed_action_fields() -> None:
    with pytest.raises(ValidationError, match="action_id"):
        HistoryMessage.model_validate(
            {"role": "user", "content": "Hello", "action_id": "ask_more"}
        )
    with pytest.raises(ValidationError, match="selected_action_id"):
        WorkspaceResponse.model_validate(
            {
                "resource_url": "https://example.com/jobs/1",
                "selected_action_id": "analyze",
                "result_type": "reply",
                "histories": [],
                "artifacts": _artifacts(),
            }
        )


def test_workspace_response_is_markdown_only_full_state() -> None:
    """Return protocol-tagged full state without v1 document rendering fields."""

    response = WorkspaceResponse(
        resource_url="https://example.com/jobs/1",
        result_type="reply",
        histories=[],
        artifacts=_artifacts(),
    )

    dumped = response.model_dump()
    assert response.protocol_version == 4
    assert response.result_type == "reply"
    assert dumped["artifacts"] == {"cv": None, "cover_letter": None}
    assert not {"document", "html", "sections"}.intersection(dumped)
    with pytest.raises(ValidationError, match="result_type"):
        WorkspaceResponse(
            resource_url="https://example.com/jobs/1",
            histories=[],
            artifacts=_artifacts(),
        )
