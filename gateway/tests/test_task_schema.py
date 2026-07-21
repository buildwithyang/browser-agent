import pytest
from pydantic import ValidationError

from app.modules.task import schema
from app.modules.task.protocol import (
    CURRENT_EXTENSION_PROTOCOL_VERSION,
    DEFAULT_EXTENSION_UPDATE_URL,
    EXTENSION_PROTOCOL_HEADER,
)
from app.modules.task.schema import (
    ExecutionMeta,
    Insight,
    PromptShortcut,
    PromptShortcutId,
    QuickInsightRequest,
    QuickInsightResponse,
    ScoreInsightCard,
    WorkspaceRequest,
    WorkspaceResponse,
    WorkspaceDescriptor,
)


def test_extension_protocol_constants_are_stable() -> None:
    """Keep the Extension wire-version and Chrome Web Store fallback stable."""

    assert CURRENT_EXTENSION_PROTOCOL_VERSION == 4
    assert EXTENSION_PROTOCOL_HEADER == "X-Agent-Bridge-Protocol-Version"
    assert DEFAULT_EXTENSION_UPDATE_URL == (
        "https://chromewebstore.google.com/detail/agent-bridge/"
        "cmajoaedbjinocbfdkebaedkdbkhbhai"
    )


def test_quick_insight_response_defaults_to_current_protocol_version() -> None:
    """Expose the required v4 protocol version on every successful insight."""

    response = QuickInsightResponse(
        request=QuickInsightRequest(url="https://example.com"),
        insight=Insight(title="Summary"),
        shortcuts=[PromptShortcut(id="ask_more", title="Ask More", prompt="")],
        workspace=WorkspaceDescriptor(resource_url="https://example.com/"),
        meta=ExecutionMeta(),
    )

    assert response.protocol_version == CURRENT_EXTENSION_PROTOCOL_VERSION


def test_quick_insight_request_has_no_public_agent_field() -> None:
    request = QuickInsightRequest(url="https://example.com")

    assert "agent" not in request.model_dump()
    assert request.lang == "auto"


def test_prompt_shortcut_contract_is_strict_and_stable() -> None:
    """Keep localized editable drafts on one closed stable-id schema."""

    shortcuts = [
        PromptShortcut(id="analyze", title="分析岗位", prompt="分析岗位"),
        PromptShortcut(id="tailor_resume", title="定制简历", prompt="定制简历"),
        PromptShortcut(id="write_cover_letter", title="撰写求职信", prompt="撰写求职信"),
        PromptShortcut(id="ask_more", title="继续提问", prompt=""),
    ]

    assert [shortcut.id for shortcut in shortcuts] == list(PromptShortcutId)
    assert all(shortcut.title for shortcut in shortcuts)
    assert all(shortcut.prompt for shortcut in shortcuts[:-1])
    assert shortcuts[-1].prompt == ""
    with pytest.raises(ValidationError, match="unexpected"):
        PromptShortcut.model_validate(
            {"id": "ask_more", "title": "Ask More", "prompt": "", "unexpected": True}
        )


def test_prompt_shortcut_allows_empty_ask_more_prompt() -> None:
    shortcut = PromptShortcut(
        id=PromptShortcutId.ASK_MORE,
        title="继续提问",
        prompt="",
    )

    assert shortcut.prompt == ""


def test_final_workspace_names_replace_every_transitional_document_type() -> None:
    """Expose only the final message-only Workspace request/response boundary."""

    request = schema.WorkspaceRequest(
        url="https://example.com/jobs/1",
        resourceUrl="https://example.com/jobs/1",
        operationId="00000000-0000-0000-0000-000000000001",
        artifacts={"cv": None, "cover_letter": None},
        message="Follow up",
    )
    response = WorkspaceResponse(
        resource_url="https://example.com/jobs/1",
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
        "Action",
        "ActionId",
        "WorkspaceTrigger",
        "UserMessageWorkspaceRequest",
        "QuickInsightActionWorkspaceRequest",
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
