import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.task.model  # noqa: F401  -- register table on Base.metadata
from app.core.db import Base
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import TaskRecordData

USER = uuid.uuid4().hex


def _make_repo(tmp_path) -> TaskRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'task.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return TaskRepository(factory)


def _record(**over) -> TaskRecordData:
    base = dict(
        id=uuid.uuid4().hex,
        user_id=USER,
        agent="job_match",
        lang="zh",
        model="gpt-4o-mini",
        status="completed",
        input_chars=1200,
        result_chars=800,
        duration_ms=1500,
        error="",
        created_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return TaskRecordData(**base)


def test_append_and_list_recent(tmp_path):
    repo = _make_repo(tmp_path)
    repo.append(_record())
    repo.append(_record(agent="summary_page", status="failed", error="boom"))

    items = repo.list_recent(user_id=USER)
    assert len(items) == 2
    assert {i.agent for i in items} == {"job_match", "summary_page"}
    failed = next(i for i in items if i.status == "failed")
    assert failed.error == "boom"


def test_anonymous_record_has_no_user(tmp_path):
    repo = _make_repo(tmp_path)
    repo.append(_record(user_id=None, agent="summary_page"))
    # 匿名记录不归任何用户，按用户查不到。
    assert repo.list_recent(user_id=USER) == []
