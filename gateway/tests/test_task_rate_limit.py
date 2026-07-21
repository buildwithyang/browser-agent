import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.task.model  # noqa: F401
from app import main
from app.agents.base import (
    AgentContext,
    AgentExecution,
    QuickInsightAgent,
    WorkspaceAgent,
    WorkspaceAgentContext,
)
from app.agents.stream import AgentCompleted, AgentDelta, AgentStatus, AgentStreamEvent
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import (
    AgentName,
    ChatResult,
    Insight,
    PromptShortcut,
    QuickInsightRequest,
    ReplyResult,
    TaskRecordData,
    WorkspaceRequest,
)
from app.modules.task.service import RateLimitError, TaskService

USER = uuid.uuid4().hex


def _repo(tmp_path) -> TaskRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'task.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return TaskRepository(factory)


def _record(**over) -> TaskRecordData:
    base = dict(
        id=uuid.uuid4().hex, user_id=USER, agent=AgentName.SUMMARY_PAGE, lang="zh",
        model="m", status="completed", input_chars=1, result_chars=1,
        duration_ms=1, error="", created_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return TaskRecordData(**base)


def test_count_since(tmp_path):
    repo = _repo(tmp_path)
    repo.append(_record())
    repo.append(_record())
    assert repo.count_since(user_id=USER, since=datetime.now(timezone.utc) - timedelta(hours=1)) == 2
    assert repo.count_since(user_id=USER, since=datetime.now(timezone.utc) + timedelta(hours=1)) == 0


def test_service_blocks_after_max(tmp_path):
    repo = _repo(tmp_path)

    class Agent(QuickInsightAgent):
        name = AgentName.SUMMARY_PAGE

        requires_resume = False

        def available_shortcuts(self, ctx: AgentContext) -> list[PromptShortcut]:
            """Declare no shortcuts for the rate-limit fake."""

            return []

        def quick_insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
            return AgentExecution(
                content=Insight(title="Summary", cards=[]),
                raw_result="ok",
                prompt="P",
                model="m",
            )

    agent = Agent()
    svc = TaskService(
        agents={AgentName.SUMMARY_PAGE: agent}, repository=repo, resume_service=None,
        default_model="m", rate_limit_max=2, rate_limit_window_seconds=3600,
    )
    task = QuickInsightRequest(url="https://x")
    svc.quick_insight(task, user_id=USER)
    svc.quick_insight(task, user_id=USER)
    with pytest.raises(RateLimitError):
        svc.quick_insight(task, user_id=USER)


def test_api_maps_rate_limit_to_429(monkeypatch):
    def boom(task, *, user_id):
        raise RateLimitError("over quota")

    monkeypatch.setattr(
        main.app.state,
        "task_service",
        SimpleNamespace(quick_insight=boom),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=main.settings, repository=None), raising=False,
    )
    client = TestClient(main.app)
    r = client.post(
        "/tasks/quick-insight",
        headers={"X-Agent-Bridge-Protocol-Version": "4"},
        json={"url": "https://x"},
    )
    assert r.status_code == 429


def test_workspace_uses_the_existing_per_user_rate_limit(tmp_path) -> None:
    """Apply the shared operational quota before each v4 Agent call."""

    repo = _repo(tmp_path)

    class Agent(WorkspaceAgent):
        """Return one deterministic reply while counting v4 calls."""

        name = AgentName.SUMMARY_PAGE
        requires_resume = False

        def __init__(self) -> None:
            """Start with no Workspace calls."""

            self.calls = 0

        def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
            """Count and return one v4 reply execution."""

            self.calls += 1
            return AgentExecution(
                content=ReplyResult(type="reply", markdown="ok"),
                raw_result="ok",
                prompt="P",
                model="m",
            )

        async def stream_chat(
            self,
            ctx: WorkspaceAgentContext,
        ) -> AsyncIterator[AgentStreamEvent]:
            """Count one streamed call and return a complete reply execution."""

            execution = self.handle_chat(ctx)
            yield AgentStatus(stage="generating_reply")
            yield AgentDelta(text="ok")
            yield AgentStatus(stage="finalizing")
            yield AgentCompleted(execution=execution)

    agent = Agent()
    service = TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},
        repository=repo,
        resume_service=None,
        default_model="m",
        rate_limit_max=1,
        rate_limit_window_seconds=3600,
    )
    request = WorkspaceRequest(
        url="https://example.com",
        resourceUrl="https://example.com/",
        operationId="00000000-0000-0000-0000-000000000001",
        histories=[],
        artifacts={"cv": None, "cover_letter": None},
        message="Question",
    )

    prepared = service.prepare_workspace_stream(request, user_id=USER)
    asyncio.run(_consume(service.stream_workspace(prepared)))
    with pytest.raises(RateLimitError):
        service.prepare_workspace_stream(request, user_id=USER)

    assert agent.calls == 1


async def _consume(events: AsyncIterator[object]) -> None:
    """Exhaust one service stream so its terminal metric is persisted."""

    async for _ in events:
        pass
