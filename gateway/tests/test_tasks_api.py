from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.modules.auth import AuthService
from app.modules.task.service import TaskService


def _wire(monkeypatch, agents):
    """Put a TaskService (+ anonymous auth) on app.state without running lifespan."""
    monkeypatch.setattr(
        main.app.state,
        "auth_service",
        AuthService(settings=main.settings, repository=None),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "task_service",
        TaskService(
            agents=agents,
            repository=None,  # 指标落库可选；测试不依赖 DB
            resume_service=None,
            default_model=main.settings.model,
        ),
        raising=False,
    )


def test_create_task_returns_result(monkeypatch):
    fake_agent = SimpleNamespace(
        build_prompt=lambda task: "PROMPT",
        run=lambda task: "## Summary\n\nThis page is about **Go** jobs.",
    )
    _wire(monkeypatch, {"summary_page": fake_agent})

    client = TestClient(main.app)
    # Mirror the extension's flat, camelCase payload.
    response = client.post(
        "/tasks",
        json={
            "url": "https://example.com/article",
            "title": "Example Article",
            "selectedText": "important section",
            "pageText": "full article text",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["agent"] == "summary_page"
    assert body["status"] == "completed"
    assert body["result"] == "## Summary\n\nThis page is about **Go** jobs."
    # The gateway also returns sanitized HTML for the extension to render.
    assert "<h2>Summary</h2>" in body["result_html"]
    assert "<strong>Go</strong>" in body["result_html"]
    # Timing + input-size fields are recorded.
    assert body["started_at"] and body["finished_at"]
    assert isinstance(body["duration_ms"], int)
    assert body["input_chars"] == len("PROMPT")  # fake agent's build_prompt output
    # 响应不再回传 prompt（含简历/页面正文）。
    assert "prompt" not in body


def test_unsupported_agent_returns_400(monkeypatch):
    _wire(monkeypatch, {})
    client = TestClient(main.app)
    response = client.post(
        "/tasks",
        json={"agent": "codex", "url": "https://example.com", "title": "x"},
    )
    assert response.status_code == 400
