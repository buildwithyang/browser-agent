from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.task.schema import (
    ActionId,
    DocumentContent,
    DocumentDraft,
    HistoryMessage,
    QuickInsightRequest,
    WorkspaceRequest,
    WorkspaceResponse,
    DOCUMENT_DRAFT_TEXT_MAX_CHARS,
    DOCUMENT_TEXT_MAX_CHARS,
)


def _history(index: int) -> dict[str, str]:
    """Build one valid wire history entry for message-limit tests."""

    return {"role": "user", "content": str(index)}


def test_workspace_accepts_tenth_input_message() -> None:
    request = WorkspaceRequest(
        url="https://example.com",
        resourceUrl="https://example.com/",
        actionId="ask_more",
        histories=[_history(index) for index in range(9)],
        message="next",
    )

    assert len(request.histories) == 9


def test_workspace_rejects_eleventh_input_message() -> None:
    with pytest.raises(
        ValidationError,
        match="histories plus current message must not exceed 10",
    ):
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId="ask_more",
            histories=[_history(index) for index in range(10)],
            message="next",
        )


@pytest.mark.parametrize("request_type", [QuickInsightRequest, WorkspaceRequest])
def test_public_task_requests_reject_agent(request_type: type) -> None:
    payload = {"url": "https://example.com", "agent": "summary_page"}
    if request_type is WorkspaceRequest:
        payload.update(
            {
                "resourceUrl": "https://example.com/",
                "actionId": "ask_more",
                "message": "question",
            }
        )

    with pytest.raises(ValidationError, match="agent"):
        request_type.model_validate(payload)


def test_history_message_has_stable_identity_and_timestamp() -> None:
    message = HistoryMessage(role="assistant", content="answer", action_id="ask_more")

    assert message.id
    assert isinstance(message.created_at, datetime)
    assert message.action_id is ActionId.ASK_MORE


def test_workspace_response_uses_document_content() -> None:
    response = WorkspaceResponse(
        resource_url="https://example.com/",
        selected_action_id="ask_more",
        histories=[],
        document=DocumentContent(text="answer"),
    )

    assert response.document is not None
    assert response.document.text == "answer"
    assert "request" not in response.model_dump()


def test_document_content_rejects_text_over_assistant_limit() -> None:
    with pytest.raises(ValidationError, match="text"):
        DocumentContent(text="a" * 100_001)


def test_any_valid_document_content_can_become_the_next_document_draft() -> None:
    document = DocumentContent(text="a" * DOCUMENT_TEXT_MAX_CHARS)

    request = WorkspaceRequest(
        url="https://example.com",
        resourceUrl="https://example.com/",
        actionId="ask_more",
        currentDocument={"kind": "resume", "title": "Draft", "text": document.text},
        message="next",
    )

    assert DOCUMENT_DRAFT_TEXT_MAX_CHARS == DOCUMENT_TEXT_MAX_CHARS
    assert request.current_document is not None
    assert request.current_document.text == document.text


def test_empty_valid_document_can_become_assistant_history() -> None:
    document = DocumentContent()

    message = HistoryMessage(role="assistant", content=document.text)

    assert message.content == ""


def test_workspace_rejects_user_history_over_input_limit() -> None:
    with pytest.raises(ValidationError, match="user history content"):
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId="ask_more",
            histories=[{"role": "user", "content": "u" * 10_001}],
            message="next",
        )


def test_workspace_rejects_current_message_over_input_limit() -> None:
    with pytest.raises(ValidationError, match="message"):
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId="ask_more",
            message="u" * 10_001,
        )


def test_document_draft_contains_only_editable_source_fields() -> None:
    draft = DocumentDraft(kind="resume", title="Draft", text="content")

    assert draft.model_dump() == {
        "kind": "resume",
        "title": "Draft",
        "text": "content",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "k" * 101),
        ("title", "t" * 501),
        ("text", "x" * 100_001),
    ],
)
def test_workspace_rejects_oversized_current_document_field(
    field: str,
    value: str,
) -> None:
    current_document = {"kind": "resume", "title": "Draft", "text": "content"}
    current_document[field] = value

    with pytest.raises(ValidationError, match=field):
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId="ask_more",
            currentDocument=current_document,
            message="next",
        )


@pytest.mark.parametrize("redundant_field", ["html", "sections"])
def test_workspace_rejects_redundant_current_document_field(
    redundant_field: str,
) -> None:
    current_document: dict[str, object] = {
        "kind": "resume",
        "title": "Draft",
        "text": "content",
        redundant_field: [] if redundant_field == "sections" else "<p>content</p>",
    }

    with pytest.raises(ValidationError, match=redundant_field):
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId="ask_more",
            currentDocument=current_document,
            message="next",
        )
