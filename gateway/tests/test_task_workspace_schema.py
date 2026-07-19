from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.task.schema import (
    ActionId,
    DocumentContent,
    HistoryMessage,
    QuickInsightRequest,
    WorkspaceRequest,
    WorkspaceResponse,
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
