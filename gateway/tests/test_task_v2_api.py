from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentContext, AgentExecution, QuickInsightAgent
from app.modules.task.schema import (
    Action,
    AgentName,
    Insight,
)


class ApiAgent(QuickInsightAgent):
    name = AgentName.SUMMARY_PAGE
    requires_resume = False

    def available_actions(self, ctx: AgentContext) -> list[Action]:
        """Declare no actions for the response-shape fake."""

        return []

    def quick_insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        return AgentExecution(
            content=Insight(title="Page Summary", cards=[]),
            raw_result="summary",
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
        headers={"X-Agent-Bridge-Protocol-Version": "2"},
        json={"url": "https://example.com", "pageText": "Page"},
    )

    assert response.status_code == 200
    assert response.json()["insight"]["title"] == "Page Summary"
    assert response.json()["protocol_version"] == 2
    assert "document" not in response.json()
