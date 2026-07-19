from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.agents.summary_page import SummaryPageAgent
from app.modules.task.schema import (
    Action,
    AgentName,
    DocumentContent,
    Insight,
    TextInsightCard,
)


class LegacyAgent(TaskAgent):
    name = AgentName.SUMMARY_PAGE

    def actions(self, ctx: AgentContext) -> list[Action]:
        """Declare no actions for the deprecated transport adapter test."""

        return []

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


def test_legacy_tasks_suppresses_new_workspace_actions(monkeypatch) -> None:
    """Do not send new Workspace Actions to an extension that calls the removed route."""

    def fake_create(**_kwargs: object) -> SimpleNamespace:
        """Return one deterministic summary through the real SummaryPageAgent."""

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Legacy summary")
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    service = main.TaskService(
        agents={
            AgentName.SUMMARY_PAGE: SummaryPageAgent(client=client, model="fake")
        },
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
    assert response.json()["actions"] == []
