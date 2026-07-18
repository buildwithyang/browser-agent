import uuid
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.modules.task.model  # noqa: F401  -- register table on Base.metadata
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.core.db import Base
from app.modules.task.model import TaskRecordModel
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import AgentName, DocumentContent, Insight, QuickInsightRequest
from app.modules.task.service import TaskService

USER = uuid.uuid4().hex


def _repo(tmp_path) -> TaskRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'task.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return TaskRepository(factory)


class FakeAgent(TaskAgent):
    name = AgentName.SUMMARY_PAGE

    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
        return AgentExecution(
            content=Insight(title="Summary", cards=[]),
            raw_result="RESULT-XYZ",
            prompt="PROMPT-XYZ",
            model="m",
        )

    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
        raise NotImplementedError


def _only_row(repo: TaskRepository) -> TaskRecordModel:
    with repo._session_scope() as db:
        rows = db.execute(select(TaskRecordModel)).scalars().all()
        assert len(rows) == 1
        return rows[0]


def _run(repo: TaskRepository, *, debug_store: bool) -> None:
    svc = TaskService(
        agents={AgentName.SUMMARY_PAGE: FakeAgent()},
        repository=repo,
        resume_service=None,
        default_model="m",
        debug_store=debug_store,
    )
    svc.quick_insight(
        QuickInsightRequest(
            url="https://ex.com/j",
            title="Go Eng",
            pageText="PAGE-BODY",
            agent=AgentName.SUMMARY_PAGE,
        ),
        user_id=USER,
    )


def test_debug_store_persists_detail(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, debug_store=True)

    row = _only_row(repo)
    assert row.url == "https://ex.com/j"
    assert row.title == "Go Eng"
    assert row.prompt == "PROMPT-XYZ"
    assert row.page_text == "PAGE-BODY"
    assert row.result == "RESULT-XYZ"


def test_default_metrics_only_leaves_detail_null(tmp_path):
    repo = _repo(tmp_path)
    _run(repo, debug_store=False)

    row = _only_row(repo)
    # 指标照常记录
    assert row.input_chars == len("PROMPT-XYZ")
    assert row.result_chars == len("RESULT-XYZ")
    # 明细字段保持 NULL(隐私)
    assert row.url is None and row.title is None
    assert row.prompt is None and row.page_text is None and row.result is None
