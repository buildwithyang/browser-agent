"""TaskService Quick Insight orchestration tests after the final cutover."""

from app.agents.base import AgentContext, AgentExecution, QuickInsightAgent
from app.modules.task.schema import (
    AgentName,
    Insight,
    PromptShortcut,
    PromptShortcutId,
    QuickInsightRequest,
)
from app.modules.task.service import TaskService


class FakeAgent(QuickInsightAgent):
    """Return deterministic Quick Insight content and Prompt Shortcuts."""

    name = AgentName.SUMMARY_PAGE
    requires_resume = False

    def available_shortcuts(self, ctx: AgentContext) -> list[PromptShortcut]:
        """Declare the fake Agent's stable Prompt Shortcut."""

        return [PromptShortcut(id=PromptShortcutId.ASK_MORE, title="Ask More", prompt="")]

    def quick_insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        """Return one typed Quick Insight execution."""

        assert isinstance(ctx.request, QuickInsightRequest)
        return AgentExecution(
            content=Insight(title="Page Summary", cards=[]),
            raw_result="summary",
            prompt="quick prompt",
            model="fake",
        )


def service() -> TaskService:
    """Build a stateless TaskService for Quick Insight tests."""

    return TaskService(
        agents={AgentName.SUMMARY_PAGE: FakeAgent()},  # type: ignore[dict-item]
        repository=None,
        resume_service=None,
        default_model="fake",
    )


def test_quick_insight_returns_typed_insight_response() -> None:
    """Return typed content, resource identity, metrics, and protocol version."""

    response = service().quick_insight(
        QuickInsightRequest(url="https://example.com", pageText="Page"),
        user_id=None,
    )

    assert response.workspace.model_dump() == {"resource_url": "https://example.com/"}
    assert response.insight.title == "Page Summary"
    assert response.shortcuts[0].id == "ask_more"
    assert response.meta.input_chars == len("quick prompt")
    assert response.protocol_version == 4


def test_quick_insight_uses_explicit_agent_operations() -> None:
    """Read Prompt Shortcuts from the dedicated QuickInsightAgent interface."""

    response = service().quick_insight(
        QuickInsightRequest(url="https://example.com", pageText="Page"),
        user_id=None,
    )

    assert response.shortcuts == [
        PromptShortcut(id=PromptShortcutId.ASK_MORE, title="Ask More", prompt="")
    ]
