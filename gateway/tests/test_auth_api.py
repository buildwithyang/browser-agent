from fastapi.testclient import TestClient

from app import main
from app.modules.auth import AuthService
from app.modules.resume import ResumeService, create_storage_provider


def _wire_state(monkeypatch, *, repository=None):
    """Set the request-scoped services on app.state without running lifespan."""
    monkeypatch.setattr(
        main.app.state,
        "settings",
        main.settings,
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "auth_service",
        AuthService(settings=main.settings, repository=repository),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "resume_service",
        ResumeService(
            settings=main.settings,
            storage=create_storage_provider(main.settings),
            repository=None,
        ),
        raising=False,
    )


def test_me_returns_null_when_not_logged_in(monkeypatch):
    _wire_state(monkeypatch)
    client = TestClient(main.app)
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["data"]["user"] is None


def test_resumes_require_authentication(monkeypatch):
    _wire_state(monkeypatch)
    client = TestClient(main.app)
    response = client.get("/resumes")
    assert response.status_code == 401


def test_login_without_casdoor_config_returns_500(monkeypatch):
    # 默认配置未填 Casdoor，/auth/login 必须明确报 "Auth is not configured"。
    _wire_state(monkeypatch)
    client = TestClient(main.app)
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 500
    assert "not configured" in response.json()["detail"].lower()
