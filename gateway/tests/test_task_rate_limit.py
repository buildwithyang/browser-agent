import uuid
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
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import (
    Action,
    ActionId,
    AgentName,
    ChatResult,
    Insight,
    QuickInsightRequest,
    ReplyResult,
    TaskRecordData,
    UserMessageWorkspaceRequest,
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

        def available_actions(self, ctx: AgentContext) -> list[Action]:
            """Declare no actions for the rate-limit fake."""

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
        headers={"X-Agent-Bridge-Protocol-Version": "3"},
        json={"url": "https://x"},
    )
    assert r.status_code == 429


def test_workspace_uses_the_existing_per_user_rate_limit(tmp_path) -> None:
    """Apply the shared operational quota before each v2 Agent call."""

    repo = _repo(tmp_path)

    class Agent(WorkspaceAgent):
        """Return one deterministic reply while counting v2 calls."""

        name = AgentName.SUMMARY_PAGE
        requires_resume = False

        def __init__(self) -> None:
            """Start with no Workspace calls."""

            self.calls = 0

        def handle_chat(self, ctx: WorkspaceAgentContext) -> AgentExecution[ChatResult]:
            """Count and return one v2 reply execution."""

            self.calls += 1
            return AgentExecution(
                content=ReplyResult(type="reply", markdown="ok"),
                raw_result="ok",
                prompt="P",
                model="m",
            )

    agent = Agent()
    service = TaskService(
        agents={AgentName.SUMMARY_PAGE: agent},
        repository=repo,
        resume_service=None,
        default_model="m",
        rate_limit_max=1,
        rate_limit_window_seconds=3600,
    )
    request = UserMessageWorkspaceRequest(
        trigger="user_message",
        url="https://example.com",
        resourceUrl="https://example.com/",
        operationId="00000000-0000-0000-0000-000000000001",
        actionId=ActionId.ASK_MORE,
        histories=[],
        artifacts={"cv": None, "cover_letter": None},
        message="Question",
    )

    service.workspace(request, user_id=USER)
    with pytest.raises(RateLimitError):
        service.workspace(request, user_id=USER)

    assert agent.calls == 1
