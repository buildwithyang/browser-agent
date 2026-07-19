from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.modules.task.schema import (
    AgentName,
    DocumentContent,
    Insight,
    WorkspaceRequest,
)


class WorkspaceAgent(TaskAgent):
    """Fake stateless agent used to exercise the workspace transition."""

    name = AgentName.SUMMARY_PAGE

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        """Quick Insight is outside the workspace endpoint test."""

        raise AssertionError("workspace endpoint must not call insight")

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        """Return a document whose text becomes the assistant message."""

        assert isinstance(ctx.request, WorkspaceRequest)
        return AgentExecution(
            content=DocumentContent(text="assistant answer", html="<p>answer</p>"),
            raw_result="assistant answer",
            prompt="workspace prompt",
            model="fake",
        )


class FailingIfCalledAgent(WorkspaceAgent):
    """Fail when invalid resource identity reaches agent execution."""

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        """Prove URL identity validation happens before agent execution."""

        raise AssertionError("agent must not run for mismatched resourceUrl")


class LongAssistantAgent(WorkspaceAgent):
    """Return a document larger than the user-input message limit."""

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        """Produce a valid 10,001-character assistant document."""

        content = "a" * 10_001
        return AgentExecution(
            content=DocumentContent(text=content),
            raw_result=content,
            prompt="workspace prompt",
            model="fake",
        )


def _wire(monkeypatch, agent: TaskAgent) -> None:
    """Install a deterministic TaskService in the FastAPI app state."""

    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},
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


def test_workspace_endpoint_returns_complete_history_transition(monkeypatch) -> None:
    _wire(monkeypatch, WorkspaceAgent())

    response = TestClient(main.app).post(
        "/tasks/workspace",
        json={
            "url": "https://example.com/article?utm_source=email&b=2&a=1#part",
            "resourceUrl": "https://example.com/article?a=1&b=2",
            "actionId": "ask_more",
            "histories": [{"role": "assistant", "content": "previous"}],
            "message": "next question",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resource_url"] == "https://example.com/article?a=1&b=2"
    assert body["selected_action_id"] == "ask_more"
    assert [item["content"] for item in body["histories"]] == [
        "previous",
        "next question",
        "assistant answer",
    ]
    assert body["histories"][-2]["role"] == "user"
    assert body["histories"][-1]["role"] == "assistant"
    assert body["histories"][-2]["action_id"] == "ask_more"
    assert body["histories"][-1]["action_id"] == "ask_more"
    assert body["histories"][-2]["id"]
    assert body["histories"][-1]["created_at"]
    assert body["document"]["text"] == "assistant answer"
    assert body["meta"]["model"] == "fake"


def test_workspace_endpoint_rejects_mismatched_resource_url(monkeypatch) -> None:
    _wire(monkeypatch, FailingIfCalledAgent())

    response = TestClient(main.app).post(
        "/tasks/workspace",
        json={
            "url": "https://example.com/real",
            "resourceUrl": "https://example.com/other",
            "actionId": "ask_more",
            "message": "question",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "resourceUrl does not match normalized url"


def test_quick_insight_rejects_invalid_url_before_agent_execution(monkeypatch) -> None:
    _wire(monkeypatch, FailingIfCalledAgent())

    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        json={"url": "not-an-absolute-url"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "url must be an absolute HTTP(S) URL"


def test_workspace_accepts_assistant_document_over_user_message_limit(
    monkeypatch,
) -> None:
    _wire(monkeypatch, LongAssistantAgent())

    response = TestClient(main.app).post(
        "/tasks/workspace",
        json={
            "url": "https://example.com/article",
            "resourceUrl": "https://example.com/article",
            "actionId": "ask_more",
            "message": "question",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["histories"][-1]["content"]) == 10_001
