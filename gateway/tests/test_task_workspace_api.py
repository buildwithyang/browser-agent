"""Protocol-v3 Workspace NDJSON API tests."""

import json
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from httpx import Response

from app import main
from app.agents.base import (
    AgentExecution,
    StreamingWorkspaceAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus, AgentStreamEvent
from app.modules.task.schema import (
    AgentName,
    ChatResult,
    ReplyResult,
    WorkspaceResultType,
)

PROTOCOL_HEADERS = {"X-Agent-Bridge-Protocol-Version": "3"}


class ApiWorkspaceAgent(WorkspaceAgent, StreamingWorkspaceAgent):
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

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Yield progress, one reply delta, and one complete execution."""

        execution = self.handle_chat(ctx)
        yield AgentStatus(stage="generating_reply")
        yield AgentDelta(text=execution.content.markdown)
        yield AgentStatus(stage="finalizing")
        yield AgentCompleted(execution=execution)


class FailingIfCalledAgent(ApiWorkspaceAgent):
    """Fail when invalid resource identity reaches Agent execution."""

    def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
        """Prove URL identity validation happens before Agent execution."""

        raise AssertionError("agent must not run for mismatched resourceUrl")

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Prove invalid resource identity never creates an Agent stream."""

        raise AssertionError("agent must not run for mismatched resourceUrl")
        yield  # pragma: no cover


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
        "operationId": "00000000-0000-0000-0000-000000000001",
        "actionId": "ask_more",
        "histories": [],
        "artifacts": {"cv": None, "cover_letter": None},
        "message": "next question",
    }
    payload.update(overrides)
    return payload


def _stream_lines(response: Response) -> list[dict[str, object]]:
    """Decode all non-empty NDJSON lines from one TestClient stream response."""

    return [json.loads(line) for line in response.iter_lines() if line]


def test_workspace_api_returns_ndjson_and_no_buffer_headers(monkeypatch) -> None:
    """Stream progress and the complete final state with anti-buffering headers."""

    _wire(monkeypatch, ApiWorkspaceAgent())
    with TestClient(main.app).stream(
        "POST",
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(
            url="https://example.com/article?utm_source=email&b=2&a=1#part",
            resourceUrl="https://example.com/article?a=1&b=2",
            histories=[{"role": "assistant", "content": "previous"}],
        ),
    ) as response:
        lines = _stream_lines(response)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-agent-bridge-protocol-version"] == "3"
    assert [line["type"] for line in lines] == [
        "started",
        "status",
        "delta",
        "status",
        "completed",
    ]
    assert [line["sequence"] for line in lines] == list(range(len(lines)))
    assert all(line["operation_id"] == _payload()["operationId"] for line in lines)
    body = lines[-1]["response"]
    assert isinstance(body, dict)
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
    assert body["protocol_version"] == 3


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


def test_workspace_maps_unexpected_preparation_failure_before_stream(monkeypatch) -> None:
    """Return an ordinary 502 when request-scoped preparation cannot complete."""

    class PreparationFailingService:
        """Fail before the API creates a StreamingResponse."""

        def prepare_workspace_stream(
            self,
            task: object,
            *,
            user_id: str | None,
        ) -> object:
            """Simulate a request-scoped dependency failure during preparation."""

            raise RuntimeError("resume repository unavailable")

    monkeypatch.setattr(
        main.app.state,
        "task_service",
        PreparationFailingService(),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "settings",
        type("Settings", (), {"require_auth": False})(),
        raising=False,
    )

    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(),
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "resume repository unavailable"


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
    with TestClient(main.app).stream(
        "POST",
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(),
    ) as response:
        lines = _stream_lines(response)

    assert response.status_code == 200
    body = lines[-1]["response"]
    assert isinstance(body, dict)
    histories = body["histories"]
    assert isinstance(histories, list)
    assert len(histories[-1]["content"]) == 10_001


def test_workspace_rejects_public_agent_field(monkeypatch) -> None:
    """Prevent callers from selecting the Gateway's internal Agent registry."""

    _wire(monkeypatch, ApiWorkspaceAgent())
    response = TestClient(main.app).post(
        "/tasks/workspace",
        headers=PROTOCOL_HEADERS,
        json=_payload(agent="job_match"),
    )

    assert response.status_code == 422
