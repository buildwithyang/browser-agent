from dataclasses import replace

from app.agents.base import (
    AgentContext,
    AgentExecution,
    TaskAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.modules.task.schema import (
    Action,
    ActionId,
    AgentName,
    ChatResult,
    DocumentContent,
    HistoryMessage,
    Insight,
    QuickInsightRequest,
    ReplyResult,
    Section,
    TaskRequest,
    WorkspaceRequest,
)
from app.modules.task.service import TaskService


class FakeAgent(TaskAgent, WorkspaceAgent):
    name = AgentName.SUMMARY_PAGE

    def actions(self, ctx: AgentContext) -> list[Action]:
        """Declare the fake Agent's stable Quick Insight action."""

        return [Action(id=ActionId.ASK_MORE, title="Ask More")]

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        assert isinstance(ctx.request, QuickInsightRequest)
        return AgentExecution(
            content=Insight(title="Page Summary", cards=[]),
            raw_result="summary",
            prompt="quick prompt",
            model="fake",
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        assert isinstance(ctx.request, TaskRequest | WorkspaceRequest)
        document = DocumentContent(
            text="document",
            html="<p>document</p>",
            sections=[Section(id="result", title="", html="<p>document</p>")],
        )
        return AgentExecution(
            content=document,
            raw_result="document",
            prompt="task prompt",
            model="fake",
        )

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Return a v2 reply without using the legacy document execution path."""

        return AgentExecution(
            content=ReplyResult(type="reply", markdown="chat reply"),
            raw_result="chat reply",
            prompt="chat prompt",
            model="fake-chat",
        )


def service() -> TaskService:
    return TaskService(
        agents={AgentName.SUMMARY_PAGE: FakeAgent()},
        repository=None,
        resume_service=None,
        default_model="fake",
    )


def test_quick_insight_returns_typed_insight_response() -> None:
    response = service().quick_insight(
        QuickInsightRequest(
            url="https://example.com",
            pageText="Page",
        ),
        user_id=None,
    )

    assert response.workspace.default_action_id == "ask_more"
    assert response.insight.title == "Page Summary"
    assert response.actions[0].id == "ask_more"
    assert response.meta.input_chars == len("quick prompt")


def test_quick_insight_uses_agent_declared_actions() -> None:
    """Read actions from TaskAgent.actions rather than AgentExecution."""

    response = service().quick_insight(
        QuickInsightRequest(url="https://example.com", pageText="Page"),
        user_id=None,
    )

    assert response.actions == [Action(id=ActionId.ASK_MORE, title="Ask More")]


def test_current_task_returns_document_response() -> None:
    response = service().execute(
        TaskRequest(
            url="https://example.com",
            actionId="ask_more",
        ),
        user_id=None,
    )

    assert response.document.text == "document"
    assert response.document.sections[0].id == "result"
    assert response.meta.input_chars == len("task prompt")


def test_workspace_ask_more_preserves_current_document() -> None:
    """Keep the latest artifact while Ask More appends to the shared history."""

    response = service().workspace(
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId=ActionId.ASK_MORE,
            histories=[HistoryMessage(role="assistant", content="Earlier answer")],
            currentDocument={
                "kind": "resume",
                "title": "Tailored Resume",
                "text": "# Existing draft\n\nGo and Agent experience.",
            },
            message="Follow up",
        ),
        user_id=None,
    )

    assert response.document is not None
    assert response.document.kind == "resume"
    assert response.document.title == "Tailored Resume"
    assert response.document.text == "# Existing draft\n\nGo and Agent experience."
    assert "<h1>Existing draft</h1>" in response.document.html
    assert response.histories[-1].content == "document"
    assert response.histories[-1].action_id is ActionId.ASK_MORE


def test_legacy_execute_and_workspace_remain_runnable_during_v2_staging() -> None:
    """Keep both temporary v1 Service methods until Task 8 migrates the API."""

    task_response = service().execute(
        TaskRequest(url="https://example.com", actionId="ask_more"),
        user_id=None,
    )
    workspace_response = service().workspace(
        WorkspaceRequest(
            url="https://example.com",
            resourceUrl="https://example.com/",
            actionId=ActionId.ASK_MORE,
            message="Follow up",
        ),
        user_id=None,
    )

    assert task_response.document.text == "document"
    assert workspace_response.document is None
    assert workspace_response.histories[-1].content == "document"
