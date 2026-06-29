import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401
from app import main
from app.core.db import Base
from app.core.session import CookieSessionMiddleware
from app.modules.auth import AuthService
from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.token_service import ExtensionTokenService

USER = uuid.uuid4().hex


def _token_service(tmp_path) -> ExtensionTokenService:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tok.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ExtensionTokenService(repository=ExtensionTokenRepository(factory), ttl_seconds=3600)


def _seed_session(client: TestClient, data: dict) -> None:
    # 用生产签名逻辑造一个合法的登录态 cookie,模拟"已登录"后再请求 /auth/logout。
    mw = CookieSessionMiddleware(app=None, secret_key=main.settings.auth_session_secret)
    name, value = mw._build_cookie(data).split(";", 1)[0].split("=", 1)
    client.cookies.set(name, value)


def test_logout_revokes_extension_tokens(monkeypatch, tmp_path):
    svc = _token_service(tmp_path)
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=main.settings, repository=None), raising=False,
    )
    monkeypatch.setattr(main.app.state, "extension_token_service", svc, raising=False)
    token = svc.issue(user_id=USER).token
    assert svc.resolve(token) == USER  # 登出前 token 有效

    client = TestClient(main.app)
    _seed_session(client, {AuthService.SESSION_USER_ID_KEY: USER})
    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json()["data"]["user"] is None
    assert svc.resolve(token) is None  # 登出后扩展 token 立即失效
