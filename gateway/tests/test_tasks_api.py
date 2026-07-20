from fastapi.testclient import TestClient

from app import main
from app.modules.task.service import TaskService


def _wire(monkeypatch) -> None:
    monkeypatch.setattr(
        main.app.state,
        "task_service",
        TaskService(
            agents={},
            repository=None,
            resume_service=None,
            default_model="fake",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "settings",
        type("Settings", (), {"require_auth": False})(),
        raising=False,
    )


def test_quick_insight_rejects_public_agent_field(monkeypatch) -> None:
    _wire(monkeypatch)

    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        headers={"X-Agent-Bridge-Protocol-Version": "3"},
        json={"agent": "codex", "url": "https://example.com"},
    )

    assert response.status_code == 422
