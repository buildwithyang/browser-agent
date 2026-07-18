from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.modules.task.schema import (
    AgentName,
    DocumentContent,
    Insight,
    TextInsightCard,
)


class LegacyAgent(TaskAgent):
    name = AgentName.SUMMARY_PAGE

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        return AgentExecution(
            content=Insight(
                title="Page Summary",
                cards=[
                    TextInsightCard(
                        id="summary",
                        title="Summary",
                        body_html="<p>Legacy summary</p>",
                    )
                ],
            ),
            raw_result="Legacy summary",
            prompt="prompt",
            model="fake",
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        raise AssertionError("legacy browser_agent should use quick insight")


def test_legacy_tasks_endpoint_adapts_new_insight_response(monkeypatch) -> None:
    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: LegacyAgent()},
        repository=None,
        resume_service=None,
        default_model="fake",
    )
    monkeypatch.setattr(main.app.state, "task_service", service, raising=False)
    monkeypatch.setattr(
        main.app.state,
        "settings",
        type("Settings", (), {"require_auth": False})(),
        raising=False,
    )

    response = TestClient(main.app).post(
        "/tasks",
        json={
            "url": "https://example.com",
            "pageText": "Page",
            "agent": "browser_agent",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["agent"] == "summary_page"
    assert body["insight"]["type"] == "summary"
    assert body["insight"]["summary_html"] == "<p>Legacy summary</p>"
    assert body["result"] == "Legacy summary"
