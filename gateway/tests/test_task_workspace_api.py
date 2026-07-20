"""Final protocol-v2 Workspace API tests."""

from fastapi.testclient import TestClient

from app import main
from app.agents.base import AgentExecution, WorkspaceAgent, WorkspaceAgentContext
from app.modules.task.schema import (
    AgentName,
    ChatResult,
    ReplyResult,
    WorkspaceResultType,
)

PROTOCOL_HEADERS = {"X-Agent-Bridge-Protocol-Version": "2"}


class ApiWorkspaceAgent(WorkspaceAgent):
    """Fake stateless Agent used to exercise the final Workspace transition."""

    name = AgentName.SUMMARY_PAGE
    requires_resume = False

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Return one Markdown-only Assistant reply."""

        return AgentExecution(
            content=ReplyResult(type=WorkspaceResultType.REPLY, markdown="assistant answer"),
            raw_result="assistant answer",
            prompt="workspace prompt",
            model="fake",
        )


class FailingIfCalledAgent(ApiWorkspaceAgent):
    """Fail when invalid resource identity reaches Agent execution."""

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Prove URL identity validation happens before Agent execution."""

        raise AssertionError("agent must not run for mismatched resourceUrl")


class LongAssistantAgent(ApiWorkspaceAgent):
    """Return Markdown larger than the user-input message limit."""

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Produce a valid 10,001-character Assistant reply."""

        content = "a" * 10_001
        return AgentExecution(
            content=ReplyResult(type=WorkspaceResultType.REPLY, markdown=content),
            raw_result=content,
            prompt="workspace prompt",
            model="fake",
        )


def _wire(monkeypatch, agent: WorkspaceAgent) -> None:
    """Install a deterministic TaskService in the FastAPI app state."""

    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},  # type: ignore[dict-item]
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


def _payload(**overrides: object) -> dict[str, object]:
    """Build one minimum valid final Workspace user-message request."""

    payload: dict[str, object] = {
        "trigger": "user_message",
        "url": "https://example.com/article",
        "resourceUrl": "https://example.com/article",
        "actionId": "ask_more",
        "histories": [],
        "artifacts": {"cv": None, "cover_letter": None},
        "message": "next question",
    }
    payload.update(overrides)
    return payload


def test_workspace_endpoint_returns_complete_final_state(monkeypatch) -> None:
    """Return trigger-reduced histories, artifacts and result type without documents."""

    _wire(monkeypatch, ApiWorkspaceAgent())
    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(
            url="https://example.com/article?utm_source=email&b=2&a=1#part",
            resourceUrl="https://example.com/article?a=1&b=2",
            histories=[{"role": "assistant", "content": "previous"}],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resource_url"] == "https://example.com/article?a=1&b=2"
    assert body["selected_action_id"] == "ask_more"
    assert body["result_type"] == "reply"
    assert [item["content"] for item in body["histories"]] == [
        "previous",
        "next question",
        "assistant answer",
    ]
    assert body["artifacts"] == {"cv": None, "cover_letter": None}
    assert not {"document", "html", "sections"}.intersection(body)
    assert body["protocol_version"] == 2


def test_workspace_endpoint_rejects_mismatched_resource_url(monkeypatch) -> None:
    """Map resource identity mismatches to 400 before Agent execution."""

    _wire(monkeypatch, FailingIfCalledAgent())
    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(
            url="https://example.com/real",
            resourceUrl="https://example.com/other",
        ),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "resourceUrl does not match normalized url"


def test_quick_insight_rejects_invalid_url_before_agent_execution(monkeypatch) -> None:
    """Keep URL normalization errors inside the accepted protocol response."""

    _wire(monkeypatch, FailingIfCalledAgent())
    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        headers=PROTOCOL_HEADERS,
        json={"url": "not-an-absolute-url"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "url must be an absolute HTTP(S) URL"


def test_workspace_accepts_assistant_reply_over_user_message_limit(monkeypatch) -> None:
    """Apply the larger Assistant Markdown cap to reducer output."""

    _wire(monkeypatch, LongAssistantAgent())
    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(),
    )

    assert response.status_code == 200
    assert len(response.json()["histories"][-1]["content"]) == 10_001


def test_workspace_rejects_public_agent_field(monkeypatch) -> None:
    """Prevent callers from selecting the Gateway's internal Agent registry."""

    _wire(monkeypatch, ApiWorkspaceAgent())
    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(agent="job_match"),
    )

    assert response.status_code == 422
