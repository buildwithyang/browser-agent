import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401
from app import main
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.auth.api import require_auth_user
from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.schema import AuthUser
from app.modules.auth.token_service import ExtensionTokenService

USER = uuid.uuid4().hex


def _service(tmp_path) -> ExtensionTokenService:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tok.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ExtensionTokenService(repository=ExtensionTokenRepository(factory), ttl_seconds=3600)


def _fake_user() -> AuthUser:
    now = datetime.now(timezone.utc)
    return AuthUser(
        user_id=USER, provider="casdoor", provider_subject="s", created_at=now, updated_at=now
    )


def test_issue_requires_login(monkeypatch, tmp_path):
    monkeypatch.setattr(main.app.state, "extension_token_service", _service(tmp_path), raising=False)
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=main.settings, repository=None), raising=False,
    )
    client = TestClient(main.app)
    assert client.post("/auth/extension-token").status_code == 401


def test_issue_list_revoke_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(main.app.state, "extension_token_service", _service(tmp_path), raising=False)
    monkeypatch.setitem(main.app.dependency_overrides, require_auth_user, _fake_user)
    client = TestClient(main.app)

    issued = client.post("/auth/extension-token").json()["data"]
    assert issued["token"].startswith("ext_")
    assert issued["expires_at"]

    items = client.get("/auth/extension-tokens").json()["data"]["items"]
    assert len(items) == 1
    assert "token" not in items[0] and "token_hash" not in items[0]
    token_id = items[0]["id"]

    after = client.delete(f"/auth/extension-tokens/{token_id}").json()["data"]["items"]
    assert after[0]["revoked"] is True
