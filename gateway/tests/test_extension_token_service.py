import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401
from app.core.db import Base
from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.token_service import ExtensionTokenService

USER = uuid.uuid4().hex


def _service(tmp_path, ttl_seconds=3600) -> ExtensionTokenService:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tok.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ExtensionTokenService(repository=ExtensionTokenRepository(factory), ttl_seconds=ttl_seconds)


def test_issue_returns_prefixed_token_and_future_expiry(tmp_path):
    svc = _service(tmp_path)
    issued = svc.issue(user_id=USER, label="浏览器扩展")
    assert issued.token.startswith("ext_")
    assert len(issued.token) > 20


def test_resolve_roundtrip_and_touches_last_used(tmp_path):
    svc = _service(tmp_path)
    token = svc.issue(user_id=USER).token
    assert svc.resolve(token) == USER
    # last_used_at now populated
    info = svc.list_for_user(USER)[0]
    assert info.last_used_at is not None


def test_resolve_rejects_unknown_expired_revoked(tmp_path):
    svc = _service(tmp_path)
    assert svc.resolve("ext_nope") is None
    assert svc.resolve("") is None

    expired = _service(tmp_path, ttl_seconds=-1)
    assert expired.resolve(expired.issue(user_id=USER).token) is None

    token = svc.issue(user_id=USER).token
    tid = svc.list_for_user(USER)[0].id
    assert svc.revoke(user_id=USER, token_id=tid) is True
    assert svc.resolve(token) is None


def test_revoke_all_for_user_invalidates_resolve(tmp_path):
    # 登出后,该用户之前签发的所有扩展 token 都应再也解析不出 user_id。
    svc = _service(tmp_path)
    t1 = svc.issue(user_id=USER).token
    t2 = svc.issue(user_id=USER).token
    assert svc.revoke_all_for_user(USER) == 2
    assert svc.resolve(t1) is None
    assert svc.resolve(t2) is None


def test_list_for_user_hides_secret(tmp_path):
    svc = _service(tmp_path)
    svc.issue(user_id=USER)
    info = svc.list_for_user(USER)[0]
    dumped = info.model_dump()
    assert "token" not in dumped and "token_hash" not in dumped
