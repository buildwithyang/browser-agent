from dataclasses import replace

from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.modules.task.schema import (
    Action,
    AgentName,
    DocumentContent,
    Insight,
    QuickInsightRequest,
    Section,
    TaskRequest,
)
from app.modules.task.service import TaskService


class FakeAgent(TaskAgent):
    name = AgentName.SUMMARY_PAGE

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        assert isinstance(ctx.request, QuickInsightRequest)
        return AgentExecution(
            content=Insight(title="Page Summary", cards=[]),
            actions=[Action(id="ask_more", title="Ask more")],
            raw_result="summary",
            prompt="quick prompt",
            model="fake",
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        assert isinstance(ctx.request, TaskRequest)
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
            agent=AgentName.BROWSER_AGENT,
        ),
        user_id=None,
    )

    assert response.request.agent is AgentName.SUMMARY_PAGE
    assert response.insight.title == "Page Summary"
    assert response.actions[0].id == "ask_more"
    assert response.meta.input_chars == len("quick prompt")


def test_current_task_returns_document_response() -> None:
    response = service().execute(
        TaskRequest(
            url="https://example.com",
            actionId="ask_more",
            agent=AgentName.SUMMARY_PAGE,
        ),
        user_id=None,
    )

    assert response.document.text == "document"
    assert response.document.sections[0].id == "result"
    assert response.meta.input_chars == len("task prompt")
