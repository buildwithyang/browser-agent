"""Protocol-v3 Workspace NDJSON API tests."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from starlette.requests import Request
from starlette.types import Message, Scope

from app import main
from app.agents.base import (
    AgentExecution,
    StreamingWorkspaceAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus, AgentStreamEvent
from app.modules.task.api import create_workspace_task
from app.modules.task.schema import (
    AgentName,
    ChatResult,
    ReplyResult,
    TaskRecordData,
    UserMessageWorkspaceRequest,
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


class ApiCloseTrackingAgent(ApiWorkspaceAgent):
    """Record deterministic Agent iterator cleanup at the HTTP boundary."""

    def __init__(self) -> None:
        """Start with no stream cleanup calls."""

        self.close_calls = 0

    async def stream_chat(
        self,
        ctx: WorkspaceAgentContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Count finalization of the Agent iterator consumed by TaskService."""

        try:
            async for event in super().stream_chat(ctx):
                yield event
        finally:
            self.close_calls += 1


class ApiRecordingRepository:
    """Capture TaskService terminal metrics for direct ASGI assertions."""

    def __init__(self) -> None:
        """Start with no terminal records."""

        self.records: list[TaskRecordData] = []

    def append(self, record: TaskRecordData) -> None:
        """Capture one terminal task record."""

        self.records.append(record)


def _wire(
    monkeypatch,
    agent: WorkspaceAgent,
    repository: ApiRecordingRepository | None = None,
) -> None:
    """Install a deterministic TaskService in the FastAPI app state."""

    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},  # type: ignore[dict-item]
        repository=repository,  # type: ignore[arg-type]
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

    repository = ApiRecordingRepository()
    agent = ApiCloseTrackingAgent()
    _wire(monkeypatch, agent, repository)
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
    assert agent.close_calls == 1
    assert [record.status for record in repository.records] == ["completed"]


@pytest.mark.parametrize("cancel_event", ["status", "completed"])
def test_workspace_response_send_cancellation_closes_service_stream(
    monkeypatch,
    cancel_event: str,
) -> None:
    """Commit only interruption metrics when any ASGI event send is cancelled."""

    repository = ApiRecordingRepository()
    agent = ApiCloseTrackingAgent()
    service = main.TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},  # type: ignore[dict-item]
        repository=repository,  # type: ignore[arg-type]
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
    monkeypatch.setattr(main.app.state, "auth_service", None, raising=False)
    monkeypatch.setattr(main.app.state, "extension_token_service", None, raising=False)

    async def execute_response() -> tuple[bool, int, tuple[str, ...], tuple[str, ...]]:
        """Drive the actual response call and snapshot cleanup before loop shutdown."""

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/tasks/workspace",
            "raw_path": b"/tasks/workspace",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
            "app": main.app,
        }

        async def receive() -> Message:
            """Block unless Request.is_disconnected performs its non-blocking probe."""

            await asyncio.Future()
            raise AssertionError("receive should remain blocked")

        request = Request(scope, receive)
        task = UserMessageWorkspaceRequest.model_validate(_payload())
        response = await create_workspace_task(task, request)
        sent_types: list[str] = []

        async def cancel_on_event(message: Message) -> None:
            """Cancel response delivery while Starlette is sending the selected event."""

            body = message.get("body", b"")
            if message["type"] != "http.response.body" or not body:
                return
            event_type = json.loads(bytes(body))["type"]
            sent_types.append(event_type)
            if event_type == cancel_event:
                raise asyncio.CancelledError

        cancelled = False
        try:
            await response(scope, receive, cancel_on_event)
        except asyncio.CancelledError:
            cancelled = True
        return (
            cancelled,
            agent.close_calls,
            tuple(sent_types),
            tuple(record.error for record in repository.records),
        )

    cancelled, close_calls, sent_types, errors = asyncio.run(execute_response())

    assert cancelled is True
    assert sent_types[-1] == cancel_event
    assert close_calls == 1
    assert errors == ("stream_interrupted",)


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


def test_workspace_preparation_runs_outside_the_asgi_event_loop(monkeypatch) -> None:
    """Offload synchronous rate-limit and CV preparation from the ASGI loop."""

    class ThreadRecordingService:
        """Record the worker used by the synchronous preparation boundary."""

        def __init__(self) -> None:
            """Start without an observed preparation thread."""

            self.preparation_thread: int | None = None

        def prepare_workspace_stream(
            self,
            task: object,
            *,
            user_id: str | None,
        ) -> object:
            """Capture the thread and return an opaque prepared request."""

            self.preparation_thread = threading.get_ident()
            return object()

        async def stream_workspace(self, prepared: object) -> AsyncIterator[object]:
            """Expose an unused async iterator required by the response boundary."""

            if False:  # pragma: no cover - response body is not consumed here.
                yield prepared

    service = ThreadRecordingService()
    monkeypatch.setattr(main.app.state, "task_service", service, raising=False)
    monkeypatch.setattr(
        main.app.state,
        "settings",
        type("Settings", (), {"require_auth": False})(),
        raising=False,
    )
    monkeypatch.setattr(main.app.state, "auth_service", None, raising=False)
    monkeypatch.setattr(main.app.state, "extension_token_service", None, raising=False)

    async def create_response() -> int:
        """Create the response and return the event-loop thread identity."""

        loop_thread = threading.get_ident()
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/tasks/workspace",
            "raw_path": b"/tasks/workspace",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
            "app": main.app,
        }

        async def receive() -> Message:
            """Return a disconnected marker if Request probes the empty body."""

            return {"type": "http.disconnect"}

        request = Request(scope, receive)
        task = UserMessageWorkspaceRequest.model_validate(_payload())
        await create_workspace_task(task, request)
        return loop_thread

    loop_thread = asyncio.run(create_response())

    assert service.preparation_thread is not None
    assert service.preparation_thread != loop_thread


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
