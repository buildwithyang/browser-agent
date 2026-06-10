from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.storage.tasks import JsonlTaskStore


def test_create_task_returns_result(tmp_path, monkeypatch):
    fake_agent = SimpleNamespace(
        build_prompt=lambda task: "PROMPT",
        run=lambda task: "## Summary\n\nThis page is about **Go** jobs.",
    )
    monkeypatch.setitem(main.agents, "summary_page", fake_agent)
    monkeypatch.setattr(main, "store", JsonlTaskStore(tmp_path / "tasks.jsonl"))

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
    # Timing fields are recorded.
    assert body["started_at"] and body["finished_at"]
    assert isinstance(body["duration_ms"], int)


def test_unsupported_agent_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", JsonlTaskStore(tmp_path / "tasks.jsonl"))
    client = TestClient(main.app)
    response = client.post(
        "/tasks",
        json={
            "agent": "codex",
            "url": "https://example.com",
            "title": "x",
        },
    )
    assert response.status_code == 400
