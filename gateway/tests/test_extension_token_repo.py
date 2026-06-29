import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.model  # noqa: F401  -- register tables on Base.metadata
from app.core.db import Base
from app.modules.auth.repo import ExtensionTokenRepository

USER = uuid.uuid4().hex
OTHER = uuid.uuid4().hex


def _repo(tmp_path) -> ExtensionTokenRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tok.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ExtensionTokenRepository(factory)


def _insert(repo, *, user_id=USER, token_hash="h", label="dev", ttl_seconds=3600):
    token_id = uuid.uuid4().hex
    repo.insert(
        token_id=token_id,
        user_id=user_id,
        token_hash=token_hash,
        label=label,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    return token_id


def test_insert_and_get_by_hash(tmp_path):
    repo = _repo(tmp_path)
    _insert(repo, token_hash="abc")
    row = repo.get_by_hash("abc")
    assert row is not None and row.user_id == USER and row.revoked is False
    assert repo.get_by_hash("missing") is None


def test_touch_last_used(tmp_path):
    repo = _repo(tmp_path)
    tid = _insert(repo, token_hash="abc")
    assert repo.get_by_hash("abc").last_used_at is None
    repo.touch_last_used(tid, datetime.now(timezone.utc))
    assert repo.get_by_hash("abc").last_used_at is not None


def test_list_by_user_excludes_others(tmp_path):
    repo = _repo(tmp_path)
    _insert(repo, token_hash="a")
    _insert(repo, token_hash="b")
    _insert(repo, user_id=OTHER, token_hash="c")
    rows = repo.list_by_user(USER)
    assert len(rows) == 2
    assert all(r.user_id == USER for r in rows)


def test_revoke_only_owned(tmp_path):
    repo = _repo(tmp_path)
    tid = _insert(repo, token_hash="a")
    assert repo.revoke(user_id=OTHER, token_id=tid) is False  # not owner
    assert repo.get_by_hash("a").revoked is False
    assert repo.revoke(user_id=USER, token_id=tid) is True
    assert repo.get_by_hash("a").revoked is True


def test_revoke_all_for_user(tmp_path):
    repo = _repo(tmp_path)
    _insert(repo, token_hash="a")
    _insert(repo, token_hash="b")
    _insert(repo, user_id=OTHER, token_hash="c")
    # 登出时一次性吊销该用户全部 token；返回实际新吊销的条数，他人 token 不受影响。
    assert repo.revoke_all_for_user(USER) == 2
    assert repo.get_by_hash("a").revoked is True
    assert repo.get_by_hash("b").revoked is True
    assert repo.get_by_hash("c").revoked is False
