import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401
from app import main
from app.agents.base import AgentContext, AgentExecution, TaskAgent
from app.config import Settings
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.token_service import ExtensionTokenService
from app.modules.task.schema import Action, AgentName, DocumentContent, Insight
from app.modules.task.service import TaskService

USER = uuid.uuid4().hex


def _token_service(tmp_path) -> ExtensionTokenService:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tok.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ExtensionTokenService(repository=ExtensionTokenRepository(factory), ttl_seconds=3600)


def _wire(monkeypatch, *, settings, token_service):
    monkeypatch.setattr(main.app.state, "settings", settings, raising=False)
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=settings, repository=None), raising=False,
    )
    monkeypatch.setattr(
        main.app.state, "extension_token_service", token_service, raising=False
    )
    class FakeAgent(TaskAgent):
        name = AgentName.SUMMARY_PAGE

        def actions(self, ctx: AgentContext) -> list[Action]:
            """Declare no actions for authentication boundary tests."""

            return []

        def insight(self, ctx: AgentContext) -> AgentExecution[Insight]:
            return AgentExecution(
                content=Insight(title="Summary", cards=[]),
                raw_result="ok",
                prompt="P",
                model="m",
            )

        def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]:
            raise NotImplementedError

    fake_agent = FakeAgent()
    monkeypatch.setattr(
        main.app.state, "task_service",
        TaskService(
            agents={AgentName.SUMMARY_PAGE: fake_agent},
            repository=None,
            resume_service=None,
            default_model=settings.model_router.default_model,
        ),
        raising=False,
    )


def test_require_auth_blocks_anonymous(monkeypatch, tmp_path):
    _wire(monkeypatch, settings=Settings(require_auth=True), token_service=_token_service(tmp_path))
    client = TestClient(main.app)
    r = client.post("/tasks/quick-insight", json={"url": "https://x", "pageText": "y"})
    assert r.status_code == 401


def test_require_auth_allows_valid_bearer(monkeypatch, tmp_path):
    svc = _token_service(tmp_path)
    _wire(monkeypatch, settings=Settings(require_auth=True), token_service=svc)
    token = svc.issue(user_id=USER).token
    client = TestClient(main.app)
    r = client.post(
        "/tasks/quick-insight",
        headers={"Authorization": f"Bearer {token}"},
        json={"url": "https://x", "pageText": "y"},
    )
    assert r.status_code == 200
    assert r.json()["meta"]["status"] == "completed"


def test_self_hosted_allows_anonymous(monkeypatch, tmp_path):
    _wire(monkeypatch, settings=Settings(require_auth=False), token_service=_token_service(tmp_path))
    client = TestClient(main.app)
    r = client.post("/tasks/quick-insight", json={"url": "https://x", "pageText": "y"})
    assert r.status_code == 200
