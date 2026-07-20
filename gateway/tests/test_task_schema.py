import pytest
from pydantic import ValidationError

from app.modules.task import schema
from app.modules.task.protocol import (
    CURRENT_EXTENSION_PROTOCOL_VERSION,
    DEFAULT_EXTENSION_UPDATE_URL,
    EXTENSION_PROTOCOL_HEADER,
)
from app.modules.task.schema import (
    Action,
    ExecutionMeta,
    Insight,
    QuickInsightRequest,
    QuickInsightResponse,
    ScoreInsightCard,
    WorkspaceRequest,
    WorkspaceResponse,
    WorkspaceDescriptor,
)


def test_extension_protocol_constants_are_stable() -> None:
    """Keep the Extension wire-version and Chrome Web Store fallback stable."""

    assert CURRENT_EXTENSION_PROTOCOL_VERSION == 2
    assert EXTENSION_PROTOCOL_HEADER == "X-Agent-Bridge-Protocol-Version"
    assert DEFAULT_EXTENSION_UPDATE_URL == (
        "https://chromewebstore.google.com/detail/agent-bridge/"
        "cmajoaedbjinocbfdkebaedkdbkhbhai"
    )


def test_quick_insight_response_defaults_to_current_protocol_version() -> None:
    """Expose the required v2 protocol version on every successful insight."""

    response = QuickInsightResponse(
        request=QuickInsightRequest(url="https://example.com"),
        insight=Insight(title="Summary"),
        actions=[Action(id="ask_more", title="Ask More")],
        workspace=WorkspaceDescriptor(
            resource_url="https://example.com/",
            default_action_id="ask_more",
        ),
        meta=ExecutionMeta(),
    )

    assert response.protocol_version == CURRENT_EXTENSION_PROTOCOL_VERSION


def test_quick_insight_request_has_no_public_agent_field() -> None:
    request = QuickInsightRequest(url="https://example.com")

    assert "agent" not in request.model_dump()
    assert request.lang == "auto"


def test_final_workspace_names_replace_every_transitional_document_type() -> None:
    """Expose only the final discriminated Workspace request/response boundary."""

    request = schema.UserMessageWorkspaceRequest(
        trigger="user_message",
        url="https://example.com/jobs/1",
        resourceUrl="https://example.com/jobs/1",
        actionId="ask_more",
        artifacts={"cv": None, "cover_letter": None},
        message="Follow up",
    )
    response = WorkspaceResponse(
        resource_url="https://example.com/jobs/1",
        selected_action_id="ask_more",
        result_type="reply",
        histories=[],
        artifacts={"cv": None, "cover_letter": None},
    )

    assert request.message == "Follow up"
    assert response.result_type == "reply"
    for deleted_name in (
        "TaskRequest",
        "TaskResponse",
        "DocumentDraft",
        "DocumentContent",
        "Section",
        "WorkspaceChatRequest",
        "WorkspaceChatResponse",
    ):
        assert not hasattr(schema, deleted_name)


def test_quick_insight_request_rejects_internal_agent_name() -> None:
    with pytest.raises(ValidationError, match="agent"):
        QuickInsightRequest(url="https://example.com", agent="browser_agent")


def test_score_card_rejects_score_outside_range() -> None:
    with pytest.raises(ValidationError):
        ScoreInsightCard(
            id="decision",
            title="Decision",
            score=101,
            recommendation="apply",
            reason="Too high",
        )
