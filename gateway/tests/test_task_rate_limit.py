import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.task.model  # noqa: F401
from app import main
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import AgentName, TaskCreate, TaskRecordData
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
    agent = SimpleNamespace(build_prompt=lambda task: "P", run=lambda task: "ok")
    svc = TaskService(
        agents={AgentName.SUMMARY_PAGE: agent}, repository=repo, resume_service=None,
        default_model="m", rate_limit_max=2, rate_limit_window_seconds=3600,
    )
    task = TaskCreate(url="https://x")
    svc.run(task, user_id=USER)
    svc.run(task, user_id=USER)
    with pytest.raises(RateLimitError):
        svc.run(task, user_id=USER)


def test_api_maps_rate_limit_to_429(monkeypatch):
    def boom(task, *, user_id):
        raise RateLimitError("over quota")

    monkeypatch.setattr(main.app.state, "task_service", SimpleNamespace(run=boom), raising=False)
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=main.settings, repository=None), raising=False,
    )
    client = TestClient(main.app)
    r = client.post("/tasks", json={"url": "https://x"})
    assert r.status_code == 429
