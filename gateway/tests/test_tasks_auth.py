import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401
from app import main
from app.config import Settings
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.token_service import ExtensionTokenService
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
    fake_agent = SimpleNamespace(build_prompt=lambda task: "P", run=lambda task: "## ok")
    monkeypatch.setattr(
        main.app.state, "task_service",
        TaskService(
            agents={"summary_page": fake_agent},
            repository=None,
            resume_service=None,
            default_model=settings.model,
        ),
        raising=False,
    )


def test_require_auth_blocks_anonymous(monkeypatch, tmp_path):
    _wire(monkeypatch, settings=Settings(require_auth=True), token_service=_token_service(tmp_path))
    client = TestClient(main.app)
    r = client.post("/tasks", json={"url": "https://x", "pageText": "y"})
    assert r.status_code == 401


def test_require_auth_allows_valid_bearer(monkeypatch, tmp_path):
    svc = _token_service(tmp_path)
    _wire(monkeypatch, settings=Settings(require_auth=True), token_service=svc)
    token = svc.issue(user_id=USER).token
    client = TestClient(main.app)
    r = client.post(
        "/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"url": "https://x", "pageText": "y"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_self_hosted_allows_anonymous(monkeypatch, tmp_path):
    _wire(monkeypatch, settings=Settings(require_auth=False), token_service=_token_service(tmp_path))
    client = TestClient(main.app)
    r = client.post("/tasks", json={"url": "https://x", "pageText": "y"})
    assert r.status_code == 200
