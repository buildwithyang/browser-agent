from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.modules.auth import AuthService
from app.modules.resume import ResumeService, create_storage_provider

# 受控的测试配置:不读开发者的 .env(否则 Casdoor / OSS 一旦配上就会改变这些断言)。
# 默认即「无 Casdoor、storage=fake」。
TEST_SETTINGS = Settings()


def _wire_state(monkeypatch, *, repository=None):
    """Set the request-scoped services on app.state without running lifespan."""
    monkeypatch.setattr(main.app.state, "settings", TEST_SETTINGS, raising=False)
    monkeypatch.setattr(
        main.app.state,
        "auth_service",
        AuthService(settings=TEST_SETTINGS, repository=repository),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "resume_service",
        ResumeService(
            settings=TEST_SETTINGS,
            storage=create_storage_provider(TEST_SETTINGS),
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
