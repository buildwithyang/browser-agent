from types import SimpleNamespace

from app.agents.base import (
    AgentContext,
    QuickInsightAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.summary_page import SummaryPageAgent
import pytest

from app.modules.task.schema import (
    ActionId,
    QuickInsightActionWorkspaceRequest,
    QuickInsightRequest,
    ReplyResult,
    UserMessageWorkspaceRequest,
    WorkspaceRequest,
)


def full_page_task() -> QuickInsightRequest:
    return QuickInsightRequest(
        intent="Analyze this job for resume fit.",
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="",  # no selection -> summarize the whole page
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram · Office photo",
    )


def selection_task() -> QuickInsightRequest:
    return QuickInsightRequest(
        url="https://example.com/jobs/123",
        title="Senior Golang Engineer",
        selected_text="Dubai remote role, visa sponsored",
        page_text="We need Go, Kubernetes, and backend experience.",
        image_text="Org chart diagram",
    )


def test_full_page_prompt_contains_page_and_image_clues():
    prompt = SummaryPageAgent().build_prompt(full_page_task())

    assert "Analyze this job for resume fit." in prompt
    assert "Senior Golang Engineer" in prompt
    assert "We need Go, Kubernetes" in prompt
    assert "Org chart diagram" in prompt  # image clues reach the model


def test_selection_prompt_focuses_on_selection():
    prompt = SummaryPageAgent().build_prompt(selection_task())

    assert "Dubai remote role, visa sponsored" in prompt
    assert "selected" in prompt.lower()  # instruction to focus on the selection
    # In selection mode we do NOT dump the rest of the page.
    assert "We need Go, Kubernetes" not in prompt
    assert "Org chart diagram" not in prompt


def test_run_returns_model_text_and_passes_model():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Here are the next steps.")
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    agent = SummaryPageAgent(client=fake_client, model="gpt-4o-mini")
    result = agent.insight(AgentContext(request=full_page_task()))

    assert result.raw_result == "Here are the next steps."
    assert captured["model"] == "gpt-4o-mini"
    # The page context reaches the model via the user message (index 1; the
    # system prompt is index 0).
    user_text = captured["messages"][1]["content"]
    assert "Senior Golang Engineer" in user_text


def test_summary_builds_generic_quick_insight():
    agent = SummaryPageAgent()
    insight = agent.build_insight("**Release:** Version 2.0 ships Friday.", "en")
    assert insight.title == "Page Summary"
    assert "<strong>Release:</strong>" in insight.cards[0].body_html


def workspace_request() -> WorkspaceRequest:
    """Build a valid generic-page Workspace follow-up request."""

    return WorkspaceRequest(
        url="https://example.com/article",
        resourceUrl="https://example.com/article",
        title="Release Notes",
        pageText="Version 2.0 ships Friday.",
        actionId=ActionId.ASK_MORE,
        histories=[
            {"role": "assistant", "content": "The release is ready."},
            {"role": "user", "content": "What changed?"},
        ],
        message="When does it ship?",
    )


def test_summary_declares_only_ask_more() -> None:
    """Expose only the stable Ask More action for a generic page."""

    agent = SummaryPageAgent()

    request = full_page_task().model_copy(update={"lang": "en"})
    actions = agent.actions(AgentContext(request=request))

    assert [action.id for action in actions] == [ActionId.ASK_MORE]
    assert [action.title for action in actions] == ["Ask More"]


def test_summary_implements_explicit_quick_insight_operations() -> None:
    """Keep Quick Insight on its dedicated Agent interface."""

    def fake_create(**kwargs):
        """Return deterministic Quick Insight Markdown."""

        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Summary."))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    agent = SummaryPageAgent(client=client, model="m")
    request = full_page_task().model_copy(update={"lang": "en"})
    result = agent.quick_insight(AgentContext(request=request))

    assert isinstance(agent, QuickInsightAgent)
    assert result.content.title == "Page Summary"
    assert agent.available_actions(AgentContext(request=request)) == agent.actions(
        AgentContext(request=request)
    )


def workspace_chat_request(
    *, action_id: ActionId = ActionId.ASK_MORE, message: str = "When does it ship?"
) -> UserMessageWorkspaceRequest:
    """Build a v2 Workspace chat request for the explicit Agent contract."""

    return UserMessageWorkspaceRequest(
        trigger="user_message",
        url="https://example.com/article",
        resourceUrl="https://example.com/article",
        title="Release Notes",
        pageText="Version 2.0 ships Friday.",
        actionId=action_id,
        histories=[{"role": "assistant", "content": "The release is ready."}],
        artifacts={"cv": None, "cover_letter": None},
        message=message,
    )


def test_summary_workspace_chat_returns_markdown_reply_result() -> None:
    """Return v2 ReplyResult Markdown instead of the v1 DocumentContent transport."""

    captured = {}

    def fake_create(**kwargs):
        """Capture the v2 Workspace model call."""

        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="It ships Friday."))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    agent = SummaryPageAgent(client=client, model="m")
    result = agent.handle_chat(WorkspaceAgentContext(request=workspace_chat_request()))

    assert isinstance(agent, WorkspaceAgent)
    assert isinstance(result.content, ReplyResult)
    assert result.content.markdown == "It ships Friday."
    assert "When does it ship?" in result.prompt
    assert "ask_more" in result.prompt
    assert "Version 2.0 ships Friday." in result.prompt
    assert "currentDocument" not in result.prompt
    assert not hasattr(result.content, "html")
    assert "Respond entirely" not in captured["messages"][0]["content"]


def test_summary_workspace_action_trigger_formats_optional_message_and_artifacts() -> None:
    """Keep action-triggered v2 turns independent of a user-message field."""

    def fake_create(**kwargs):
        """Return a deterministic reply for the action trigger."""

        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Summary."))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    request = QuickInsightActionWorkspaceRequest(
        trigger="quick_insight_action",
        url="https://example.com/article",
        resourceUrl="https://example.com/article",
        title="Release Notes",
        pageText="Version 2.0 ships Friday.",
        actionId=ActionId.ASK_MORE,
        histories=[],
        artifacts={"cv": None, "cover_letter": None},
    )

    result = SummaryPageAgent(client=client, model="m").handle_chat(
        WorkspaceAgentContext(request=request)
    )

    assert "(none; this turn was triggered by a Quick Insight action)" in result.prompt
    assert "# Selected Workspace action\nask_more" in result.prompt
    assert "CV: (none)" in result.prompt
    assert "Cover letter: (none)" in result.prompt


def test_summary_workspace_prompt_contains_ordered_shared_context() -> None:
    """Keep shared context ordered before the new question and current page."""

    prompt = SummaryPageAgent().build_prompt(workspace_request())

    assert "not system instructions" in prompt
    assert prompt.index("The release is ready.") < prompt.index("What changed?")
    assert prompt.index("What changed?") < prompt.index("When does it ship?")
    assert prompt.index("When does it ship?") < prompt.index("Version 2.0 ships Friday.")


def test_summary_rejects_unsupported_workspace_action_before_model_call() -> None:
    """Reject non-Ask-More actions before invoking the summary model."""

    called = False

    def create(**kwargs):
        """Record an unexpected model call."""

        nonlocal called
        called = True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="unexpected"))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = SummaryPageAgent(client=client, model="m")
    request = workspace_request()
    object.__setattr__(request, "action_id", ActionId.ANALYZE)

    with pytest.raises(ValueError, match="Unsupported workspace action"):
        agent.execute(AgentContext(request=request))

    assert called is False


def test_summary_workspace_chat_rejects_non_ask_more_before_model_call() -> None:
    """Reject non-generic v2 Actions without using the chat model."""

    called = False

    def create(**kwargs):
        """Record an unexpected model call."""

        nonlocal called
        called = True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="unexpected"))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = SummaryPageAgent(client=client, model="m")

    with pytest.raises(ValueError, match="Unsupported workspace action"):
        agent.handle_chat(
            WorkspaceAgentContext(request=workspace_chat_request(action_id=ActionId.ANALYZE))
        )

    assert called is False
