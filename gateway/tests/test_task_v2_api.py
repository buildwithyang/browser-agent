from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.modules.task.schema import (
    AgentName,
    DocumentContent,
    Insight,
    Section,
)


class ApiAgent(TaskAgent):
    name = AgentName.SUMMARY_PAGE

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        return AgentExecution(
            content=Insight(title="Page Summary", cards=[]),
            raw_result="summary",
            prompt="prompt",
            model="fake",
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        return AgentExecution(
            content=DocumentContent(
                text="document",
                html="<p>document</p>",
                sections=[Section(id="result", title="", html="<p>document</p>")],
            ),
            raw_result="document",
            prompt="prompt",
            model="fake",
        )


def _wire(monkeypatch) -> None:
    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: ApiAgent()},
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


def test_quick_insight_endpoint_has_stable_response_shape(monkeypatch) -> None:
    _wire(monkeypatch)
    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        json={"url": "https://example.com", "pageText": "Page"},
    )

    assert response.status_code == 200
    assert response.json()["insight"]["title"] == "Page Summary"
    assert "document" not in response.json()


def test_current_task_endpoint_has_stable_response_shape(monkeypatch) -> None:
    _wire(monkeypatch)
    response = TestClient(main.app).post(
        "/tasks/current-task",
        json={"url": "https://example.com", "actionId": "ask_more"},
    )

    assert response.status_code == 200
    assert response.json()["document"]["text"] == "document"
    assert "insight" not in response.json()
