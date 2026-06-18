# Extension Auth — Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DB-opaque bearer-token auth for the browser extension to the gateway, plus the `REQUIRE_AUTH` switch, input caps, and per-user rate limiting on `/tasks`.

**Architecture:** Self-signed opaque tokens (`ext_<token_urlsafe(32)>`) are minted for a logged-in user via a new `POST /auth/extension-token`, stored as `sha256(token)` in a new `auth_tokens` table, and resolved on every `/tasks` request by a shared `resolve_user_id(request)` that tries `Authorization: Bearer` first then the session cookie. `REQUIRE_AUTH` gates whether anonymous `/tasks` is allowed (hosted = required, self-hosted = optional).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column), Pydantic v2, pytest (`pythonpath=["."]`), SQLite (dev) / PostgreSQL (prod). Token hashing via stdlib `hashlib`/`secrets`.

**Scope:** Gateway only. Frontend (React card) and extension (MV3 messaging) are separate plans requiring manual browser verification — out of scope here.

## Global Constraints

- Python `>=3.11`; Pydantic `>=2.7`; SQLAlchemy `>=2.0.30` — copied from `gateway/pyproject.toml`.
- **Never log token plaintext or hash** (`AGENTS.md` log-redaction rule). Tokens appear only in the issue response body.
- **Store `sha256(token)` hex, never plaintext.** Plaintext is returned to the caller exactly once, at issue time.
- All datetimes are UTC. When reading a datetime back from SQLite it may be tz-naive — treat naive as UTC before comparing (`_as_utc` helper).
- Follow existing module layout: `model.py` / `repo.py` / `service.py` / `schema.py` / `api.py` per module; repos take a `sessionmaker`; services hang off `app.state`; tests wire `app.state` via `monkeypatch.setattr(..., raising=False)`.
- Test runner: from the `gateway/` directory, `uv run pytest <path> -v`.
- `user_id` is a 32-char uuid hex string (`UUIDHexString` SQL type), matching `auth_users.user_id`.

---

### Task 1: `auth_tokens` model + repository

**Files:**
- Modify: `gateway/app/modules/auth/model.py` (add `ExtensionTokenModel`)
- Modify: `gateway/app/modules/auth/repo.py` (add `ExtensionTokenRepository`)
- Modify: `deploy/initdb/001-schema.sql` (add `auth_tokens` table)
- Test: `gateway/tests/test_extension_token_repo.py`

**Interfaces:**
- Produces:
  - `ExtensionTokenModel` (table `auth_tokens`): columns `id, user_id, token_hash, label, created_at, last_used_at, expires_at, revoked`.
  - `ExtensionTokenRepository(session_factory)` with:
    - `insert(*, token_id: str, user_id: str, token_hash: str, label: str | None, expires_at: datetime) -> None`
    - `get_by_hash(token_hash: str) -> ExtensionTokenModel | None`
    - `touch_last_used(token_id: str, when: datetime) -> None`
    - `list_by_user(user_id: str) -> list[ExtensionTokenModel]` (newest first)
    - `revoke(*, user_id: str, token_id: str) -> bool` (True if a matching, owned row was flipped)

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_extension_token_repo.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_extension_token_repo.py -v`
Expected: FAIL with `ImportError: cannot import name 'ExtensionTokenRepository'`.

- [ ] **Step 3a: Add the model**

In `gateway/app/modules/auth/model.py`, add `Boolean` to the sqlalchemy import and append the class:

```python
from sqlalchemy import Boolean, DateTime, Index, String, text  # add Boolean


class ExtensionTokenModel(Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        Index("uq_auth_tokens_token_hash", "token_hash", unique=True),
        Index("idx_auth_tokens_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUIDHexString(), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUIDHexString(), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE")
    )
```

- [ ] **Step 3b: Add the repository**

In `gateway/app/modules/auth/repo.py`, add imports and the class. The file currently imports `select`, `SQLAlchemyError`, `OrmSession`, `sessionmaker`, and `UserModel`; extend the model import:

```python
from app.modules.auth.model import ExtensionTokenModel, UserModel  # add ExtensionTokenModel
```

Append:

```python
class ExtensionTokenRepository:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    def insert(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        label: str | None,
        expires_at,
    ) -> None:
        try:
            with self._session_factory() as db:
                db.add(
                    ExtensionTokenModel(
                        id=token_id,
                        user_id=user_id,
                        token_hash=token_hash,
                        label=label,
                        expires_at=expires_at,
                    )
                )
                db.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to insert extension token: {exc}") from exc

    def get_by_hash(self, token_hash: str) -> ExtensionTokenModel | None:
        stmt = select(ExtensionTokenModel).where(
            ExtensionTokenModel.token_hash == token_hash
        ).limit(1)
        try:
            with self._session_factory() as db:
                return db.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to query extension token: {exc}") from exc

    def touch_last_used(self, token_id: str, when) -> None:
        try:
            with self._session_factory() as db:
                row = db.get(ExtensionTokenModel, token_id)
                if row is not None:
                    row.last_used_at = when
                    db.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to update extension token: {exc}") from exc

    def list_by_user(self, user_id: str) -> list[ExtensionTokenModel]:
        stmt = (
            select(ExtensionTokenModel)
            .where(ExtensionTokenModel.user_id == user_id)
            .order_by(ExtensionTokenModel.created_at.desc())
        )
        try:
            with self._session_factory() as db:
                return list(db.execute(stmt).scalars().all())
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to list extension tokens: {exc}") from exc

    def revoke(self, *, user_id: str, token_id: str) -> bool:
        try:
            with self._session_factory() as db:
                row = db.get(ExtensionTokenModel, token_id)
                if row is None or row.user_id != user_id:
                    return False
                if not row.revoked:
                    row.revoked = True
                    db.commit()
                return True
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to revoke extension token: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_extension_token_repo.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Sync the PostgreSQL schema**

In `deploy/initdb/001-schema.sql`, after the `auth_users` block (and its indexes, before the `resume` block), insert:

```sql
-- =====================================================================
-- auth_tokens：扩展 bearer token（DB opaque，可吊销 / 可解绑设备）
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.auth_tokens (
    id            VARCHAR(32) PRIMARY KEY,                         -- token 记录 ID（uuid hex）
    user_id       VARCHAR(32) NOT NULL,                            -- 归属用户（auth_users.user_id）
    token_hash    VARCHAR(64) NOT NULL,                            -- sha256(明文 token) 十六进制
    label         VARCHAR(128),                                    -- 设备/来源标识
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 签发时间
    last_used_at  TIMESTAMPTZ,                                     -- 最近使用
    expires_at    TIMESTAMPTZ NOT NULL,                            -- 过期时间（签发 + TTL）
    revoked       BOOLEAN NOT NULL DEFAULT FALSE                   -- 是否已吊销
);

-- token 校验：按 hash 唯一定位
CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_tokens_token_hash
    ON public.auth_tokens (token_hash);

-- 按用户列出 token（解绑设备 UI）
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_created_at
    ON public.auth_tokens (user_id, created_at);
```

- [ ] **Step 6: Commit**

```bash
git add gateway/app/modules/auth/model.py gateway/app/modules/auth/repo.py gateway/tests/test_extension_token_repo.py deploy/initdb/001-schema.sql
git commit -m "feat(gateway): add auth_tokens model + repository"
```

---

### Task 2: `ExtensionTokenService` + response schemas

**Files:**
- Create: `gateway/app/modules/auth/token_service.py`
- Modify: `gateway/app/modules/auth/schema.py` (add response models)
- Modify: `gateway/app/config.py` (add `extension_token_ttl_seconds`)
- Test: `gateway/tests/test_extension_token_service.py`

**Interfaces:**
- Consumes: `ExtensionTokenRepository` (Task 1).
- Produces:
  - Schemas in `schema.py`: `ExtensionTokenIssued{token: str, expires_at: datetime}`, `ExtensionTokenInfo{id, label, created_at, last_used_at, expires_at, revoked}`, `ExtensionTokenListData{items: list[ExtensionTokenInfo]}`.
  - `ExtensionTokenService(*, repository, ttl_seconds)` with:
    - `issue(*, user_id: str, label: str | None = None) -> ExtensionTokenIssued`
    - `resolve(token: str) -> str | None` (active + unexpired; touches `last_used_at`)
    - `list_for_user(user_id: str) -> list[ExtensionTokenInfo]`
    - `revoke(*, user_id: str, token_id: str) -> bool`
  - `Settings.extension_token_ttl_seconds: int` (default `2592000` = 30 days), env `EXTENSION_TOKEN_TTL_SECONDS`.

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_extension_token_service.py`:

```python
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


def test_list_for_user_hides_secret(tmp_path):
    svc = _service(tmp_path)
    svc.issue(user_id=USER)
    info = svc.list_for_user(USER)[0]
    dumped = info.model_dump()
    assert "token" not in dumped and "token_hash" not in dumped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_extension_token_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.auth.token_service'`.

- [ ] **Step 3a: Add the response schemas**

Append to `gateway/app/modules/auth/schema.py`:

```python
class ExtensionTokenIssued(BaseModel):
    token: str  # 明文，仅签发时返回这一次
    expires_at: datetime


class ExtensionTokenInfo(BaseModel):
    id: str
    label: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime
    revoked: bool


class ExtensionTokenListData(BaseModel):
    items: list[ExtensionTokenInfo]
```

- [ ] **Step 3b: Add the TTL setting**

In `gateway/app/config.py`, add the field in the `Settings` dataclass (under the `# --- 登录态 cookie` block) :

```python
    # 扩展 bearer token 有效期（秒），默认 30 天。
    extension_token_ttl_seconds: int = 30 * 24 * 3600
```

And in `from_env`, add the mapping (after `auth_frontend_redirect_url=...`):

```python
            extension_token_ttl_seconds=_get_env_int(
                "EXTENSION_TOKEN_TTL_SECONDS", cls.extension_token_ttl_seconds
            ),
```

- [ ] **Step 3c: Add the service**

Create `gateway/app/modules/auth/token_service.py`:

```python
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.modules.auth.repo import ExtensionTokenRepository
from app.modules.auth.schema import ExtensionTokenInfo, ExtensionTokenIssued


def _new_token() -> str:
    return f"ext_{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    # SQLite 读回的 datetime 可能是 naive（无 tzinfo）；按 UTC 处理。
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class ExtensionTokenService:
    """扩展 bearer token 的签发 / 校验 / 列表 / 吊销。明文只在 issue 时出现一次。"""

    def __init__(self, *, repository: ExtensionTokenRepository | None, ttl_seconds: int) -> None:
        self._repository = repository
        self._ttl_seconds = ttl_seconds

    def issue(self, *, user_id: str, label: str | None = None) -> ExtensionTokenIssued:
        if self._repository is None:
            raise RuntimeError("Extension token repository is not initialized")
        token = _new_token()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        self._repository.insert(
            token_id=uuid.uuid4().hex,
            user_id=user_id,
            token_hash=_hash_token(token),
            label=label,
            expires_at=expires_at,
        )
        return ExtensionTokenIssued(token=token, expires_at=expires_at)

    def resolve(self, token: str) -> str | None:
        if self._repository is None or not token:
            return None
        row = self._repository.get_by_hash(_hash_token(token))
        if row is None or row.revoked:
            return None
        if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
            return None
        self._repository.touch_last_used(row.id, datetime.now(timezone.utc))
        return row.user_id

    def list_for_user(self, user_id: str) -> list[ExtensionTokenInfo]:
        if self._repository is None:
            return []
        return [
            ExtensionTokenInfo(
                id=row.id,
                label=row.label,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                expires_at=row.expires_at,
                revoked=row.revoked,
            )
            for row in self._repository.list_by_user(user_id)
        ]

    def revoke(self, *, user_id: str, token_id: str) -> bool:
        if self._repository is None:
            return False
        return self._repository.revoke(user_id=user_id, token_id=token_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_extension_token_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/auth/token_service.py gateway/app/modules/auth/schema.py gateway/app/config.py gateway/tests/test_extension_token_service.py
git commit -m "feat(gateway): add ExtensionTokenService (mint/resolve/list/revoke)"
```

---

### Task 3: Extension-token endpoints (issue / list / revoke)

**Files:**
- Modify: `gateway/app/modules/auth/api.py` (3 routes + service accessor)
- Modify: `gateway/app/modules/auth/__init__.py` (export repo + service)
- Modify: `gateway/app/main.py` (wire `extension_token_service` onto `app.state`)
- Test: `gateway/tests/test_extension_token_api.py`

**Interfaces:**
- Consumes: `ExtensionTokenService` (Task 2), `require_auth_user` (existing in `auth/api.py`).
- Produces routes:
  - `POST /auth/extension-token` → `ApiResponse[ExtensionTokenIssued]`
  - `GET /auth/extension-tokens` → `ApiResponse[ExtensionTokenListData]`
  - `DELETE /auth/extension-tokens/{token_id}` → `ApiResponse[ExtensionTokenListData]`
  - `app.state.extension_token_service: ExtensionTokenService`

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_extension_token_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_extension_token_api.py -v`
Expected: FAIL — `404` on `/auth/extension-token` (route not defined) so the assertions fail.

- [ ] **Step 3a: Export repo + service from the auth package**

Replace `gateway/app/modules/auth/__init__.py` with:

```python
from app.modules.auth.repo import ExtensionTokenRepository, UserRepository
from app.modules.auth.service import AuthService
from app.modules.auth.token_service import ExtensionTokenService

__all__ = [
    "AuthService",
    "UserRepository",
    "ExtensionTokenRepository",
    "ExtensionTokenService",
]
```

- [ ] **Step 3b: Add the routes**

In `gateway/app/modules/auth/api.py`, extend the schema import and add the routes. Update the import line:

```python
from app.modules.auth.schema import (
    ApiResponse,
    AuthMeData,
    AuthUser,
    ExtensionTokenIssued,
    ExtensionTokenListData,
)
from app.modules.auth.token_service import ExtensionTokenService
```

Add a service accessor next to `get_auth_service`:

```python
def get_extension_token_service(request: Request) -> ExtensionTokenService:
    service = getattr(request.app.state, "extension_token_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Extension token service is not initialized")
    return cast(ExtensionTokenService, service)
```

Append the routes at the end of the file:

```python
@router.post("/extension-token", response_model=ApiResponse[ExtensionTokenIssued])
def issue_extension_token(
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    issued = service.issue(user_id=user.user_id, label="浏览器扩展")
    return ApiResponse(data=issued)


@router.get("/extension-tokens", response_model=ApiResponse[ExtensionTokenListData])
def list_extension_tokens(
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    return ApiResponse(data=ExtensionTokenListData(items=service.list_for_user(user.user_id)))


@router.delete("/extension-tokens/{token_id}", response_model=ApiResponse[ExtensionTokenListData])
def revoke_extension_token(
    token_id: str,
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    service.revoke(user_id=user.user_id, token_id=token_id)
    return ApiResponse(data=ExtensionTokenListData(items=service.list_for_user(user.user_id)))
```

- [ ] **Step 3c: Wire the service in main.py**

In `gateway/app/main.py`, update the auth import:

```python
from app.modules.auth import (
    AuthService,
    ExtensionTokenRepository,
    ExtensionTokenService,
    UserRepository,
)
```

Inside `lifespan`, after `user_repository = ...`, add:

```python
    extension_token_repository = (
        ExtensionTokenRepository(session_factory) if session_factory is not None else None
    )
```

And after `app.state.auth_service = ...`, add:

```python
    app.state.extension_token_service = ExtensionTokenService(
        repository=extension_token_repository,
        ttl_seconds=settings.extension_token_ttl_seconds,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_extension_token_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/auth/api.py gateway/app/modules/auth/__init__.py gateway/app/main.py gateway/tests/test_extension_token_api.py
git commit -m "feat(gateway): add extension-token issue/list/revoke endpoints"
```

---

### Task 4: `resolve_user_id` identity resolver

**Files:**
- Create: `gateway/app/modules/auth/identity.py`
- Test: `gateway/tests/test_identity.py`

**Interfaces:**
- Consumes: `app.state.extension_token_service.resolve`, `app.state.auth_service.get_current_user`.
- Produces: `resolve_user_id(request) -> str | None` — Bearer first (via token service), then session cookie (via auth service), else `None`.

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_identity.py`:

```python
from types import SimpleNamespace

from app.modules.auth.identity import resolve_user_id


class _TokenSvc:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, token):
        return self._mapping.get(token)


class _AuthSvc:
    def __init__(self, user):
        self._user = user

    def get_current_user(self, session):
        return self._user


def _req(*, headers=None, session=None, token_service=None, auth_service=None):
    state = SimpleNamespace(
        extension_token_service=token_service, auth_service=auth_service
    )
    return SimpleNamespace(app=SimpleNamespace(state=state), headers=headers or {}, session=session or {})


def test_bearer_takes_precedence():
    req = _req(headers={"Authorization": "Bearer good"}, token_service=_TokenSvc({"good": "U1"}))
    assert resolve_user_id(req) == "U1"


def test_falls_back_to_cookie_when_no_bearer():
    req = _req(token_service=_TokenSvc({}), auth_service=_AuthSvc(SimpleNamespace(user_id="U2")))
    assert resolve_user_id(req) == "U2"


def test_invalid_bearer_then_no_cookie_returns_none():
    req = _req(
        headers={"Authorization": "Bearer bad"},
        token_service=_TokenSvc({}),
        auth_service=_AuthSvc(None),
    )
    assert resolve_user_id(req) is None


def test_no_services_returns_none():
    assert resolve_user_id(_req()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.auth.identity'`.

- [ ] **Step 3: Implement the resolver**

Create `gateway/app/modules/auth/identity.py`:

```python
from __future__ import annotations

_BEARER_PREFIX = "Bearer "


def resolve_user_id(request) -> str | None:
    """解析当前请求的 user_id：先 Authorization: Bearer，再回退 session cookie。

    扩展跨站 fetch 发不出 cookie，必须走 bearer；同源 Web 调用走 cookie。
    """
    token_service = getattr(request.app.state, "extension_token_service", None)
    if token_service is not None:
        header = request.headers.get("Authorization") or ""
        if header.startswith(_BEARER_PREFIX):
            token = header[len(_BEARER_PREFIX):].strip()
            if token:
                user_id = token_service.resolve(token)
                if user_id is not None:
                    return user_id

    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is not None:
        user = auth_service.get_current_user(request.session)
        if user is not None:
            return user.user_id

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_identity.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/auth/identity.py gateway/tests/test_identity.py
git commit -m "feat(gateway): add resolve_user_id (bearer-first identity resolver)"
```

---

### Task 5: `/tasks` bearer support + `REQUIRE_AUTH` gate

**Files:**
- Modify: `gateway/app/config.py` (add `require_auth`)
- Modify: `gateway/app/modules/task/api.py` (use `resolve_user_id`, add gate)
- Test: `gateway/tests/test_tasks_auth.py`

**Interfaces:**
- Consumes: `resolve_user_id` (Task 4), `ExtensionTokenService` (Task 2), `Settings.require_auth`.
- Produces: `Settings.require_auth: bool` (default `False`), env `REQUIRE_AUTH`. `/tasks` returns 401 when `require_auth` and no identity; otherwise runs (anonymous allowed when `require_auth` is False).

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_tasks_auth.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_tasks_auth.py -v`
Expected: FAIL — `test_require_auth_blocks_anonymous` gets 200 instead of 401 (gate not implemented); and `Settings(require_auth=...)` raises `TypeError` (field missing). Add the field first if the TypeError blocks collection.

- [ ] **Step 3a: Add the config flag**

In `gateway/app/config.py`, add to `Settings` (under the cookie block, near `extension_token_ttl_seconds`):

```python
    # /tasks 是否强制登录：托管 true（须 token/cookie）；自部署 false（匿名直连，token 可选）。
    require_auth: bool = False
```

And in `from_env`:

```python
            require_auth=_get_env_bool("REQUIRE_AUTH", cls.require_auth),
```

- [ ] **Step 3b: Use the resolver + gate in the tasks route**

Replace the body of `gateway/app/modules/task/api.py` from the `_current_user_id` helper through `create_task` with:

```python
from app.modules.auth.identity import resolve_user_id


@router.post("/tasks", response_model=TaskResponse)
def create_task(task: TaskCreate, request: Request) -> TaskResponse:
    service = get_task_service(request)
    user_id = resolve_user_id(request)

    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "require_auth", False) and user_id is None:
        # 托管平台：/tasks 不接受匿名调用。
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        return service.run(task, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

Delete the now-unused `_current_user_id` function. Keep `get_task_service` as is. The top imports stay the same (the `cast`/`Request`/`HTTPException` imports remain in use).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gateway && uv run pytest tests/test_tasks_auth.py tests/test_tasks_api.py -v`
Expected: PASS (3 new + 2 existing). The existing `test_tasks_api.py` still passes because `resolve_user_id` returns `None` (no token service wired there) and `require_auth` defaults off.

- [ ] **Step 5: Commit**

```bash
git add gateway/app/config.py gateway/app/modules/task/api.py gateway/tests/test_tasks_auth.py
git commit -m "feat(gateway): /tasks bearer auth + REQUIRE_AUTH gate"
```

---

### Task 6: Input caps on `/tasks`

**Files:**
- Modify: `gateway/app/modules/task/schema.py` (max_length on text fields)
- Test: `gateway/tests/test_task_input_caps.py`

**Interfaces:**
- Produces: `TaskCreate` rejects oversized `page_text` / `selected_text` / `image_text` with HTTP 422. Module constants `PAGE_TEXT_MAX_CHARS=200_000`, `SELECTED_TEXT_MAX_CHARS=100_000`, `IMAGE_TEXT_MAX_CHARS=50_000`.

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_task_input_caps.py`:

```python
from fastapi.testclient import TestClient

from app import main
from app.modules.task.schema import PAGE_TEXT_MAX_CHARS


def test_oversized_page_text_rejected():
    client = TestClient(main.app)
    r = client.post(
        "/tasks",
        json={"url": "https://x", "pageText": "a" * (PAGE_TEXT_MAX_CHARS + 1)},
    )
    assert r.status_code == 422


def test_within_cap_accepted_by_validation():
    # 校验通过即可（无需真正执行 agent）：不应是 422。
    client = TestClient(main.app)
    r = client.post(
        "/tasks",
        json={"url": "https://x", "pageText": "a" * 100},
    )
    assert r.status_code != 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_task_input_caps.py -v`
Expected: FAIL — `ImportError: cannot import name 'PAGE_TEXT_MAX_CHARS'`.

- [ ] **Step 3: Add caps**

In `gateway/app/modules/task/schema.py`, add constants above `class TaskCreate` and apply `max_length`:

```python
# /tasks 输入封顶：防止匿名/恶意调用塞超大正文烧平台 LLM 钱。
PAGE_TEXT_MAX_CHARS = 200_000
SELECTED_TEXT_MAX_CHARS = 100_000
IMAGE_TEXT_MAX_CHARS = 50_000
```

Update the three fields:

```python
    selected_text: str = Field("", alias="selectedText", max_length=SELECTED_TEXT_MAX_CHARS)
    page_text: str = Field("", alias="pageText", max_length=PAGE_TEXT_MAX_CHARS)
    # 图片文字线索(alt / caption / aria-label),纯文本,不含图片本身。
    image_text: str = Field("", alias="imageText", max_length=IMAGE_TEXT_MAX_CHARS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_task_input_caps.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/task/schema.py gateway/tests/test_task_input_caps.py
git commit -m "feat(gateway): cap /tasks text input sizes (422 on overflow)"
```

---

### Task 7: Per-user rate limiting on `/tasks`

**Files:**
- Modify: `gateway/app/modules/task/repo.py` (add `count_since`)
- Modify: `gateway/app/modules/task/service.py` (add `RateLimitError` + enforcement)
- Modify: `gateway/app/modules/task/api.py` (map `RateLimitError` → 429)
- Modify: `gateway/app/config.py` (rate-limit settings)
- Modify: `gateway/app/main.py` (pass rate-limit settings into `TaskService`)
- Test: `gateway/tests/test_task_rate_limit.py`

**Interfaces:**
- Consumes: `TaskRepository`, `Settings`.
- Produces:
  - `TaskRepository.count_since(*, user_id: str, since: datetime) -> int`
  - `RateLimitError(RuntimeError)` in `task/service.py`
  - `TaskService(..., rate_limit_max: int = 0, rate_limit_window_seconds: int = 86400)` — enforced only when `user_id` is set, a repository exists, and `rate_limit_max > 0`.
  - `Settings.task_rate_limit_max: int = 0`, `Settings.task_rate_limit_window_seconds: int = 86400` (env `TASK_RATE_LIMIT_MAX`, `TASK_RATE_LIMIT_WINDOW_SECONDS`).
  - `/tasks` returns HTTP 429 on `RateLimitError`.

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_task_rate_limit.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.task.model  # noqa: F401
from app import main
from app.core.db import Base
from app.modules.auth import AuthService
from app.modules.task.repo import TaskRepository
from app.modules.task.schema import TaskCreate, TaskRecordData
from app.modules.task.service import RateLimitError, TaskService

USER = uuid.uuid4().hex


def _repo(tmp_path) -> TaskRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'task.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return TaskRepository(factory)


def _record(**over) -> TaskRecordData:
    base = dict(
        id=uuid.uuid4().hex, user_id=USER, agent="summary_page", lang="zh",
        model="m", status="completed", input_chars=1, result_chars=1,
        duration_ms=1, error="", created_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return TaskRecordData(**base)


def test_count_since(tmp_path):
    repo = _repo(tmp_path)
    repo.append(_record())
    repo.append(_record())
    assert repo.count_since(user_id=USER, since=datetime.now(timezone.utc) - timedelta(hours=1)) == 2
    assert repo.count_since(user_id=USER, since=datetime.now(timezone.utc) + timedelta(hours=1)) == 0


def test_service_blocks_after_max(tmp_path):
    repo = _repo(tmp_path)
    agent = SimpleNamespace(build_prompt=lambda task: "P", run=lambda task: "ok")
    svc = TaskService(
        agents={"summary_page": agent}, repository=repo, resume_service=None,
        default_model="m", rate_limit_max=2, rate_limit_window_seconds=3600,
    )
    task = TaskCreate(url="https://x")
    svc.run(task, user_id=USER)
    svc.run(task, user_id=USER)
    with pytest.raises(RateLimitError):
        svc.run(task, user_id=USER)


def test_api_maps_rate_limit_to_429(monkeypatch):
    def boom(task, *, user_id):
        raise RateLimitError("over quota")

    monkeypatch.setattr(main.app.state, "task_service", SimpleNamespace(run=boom), raising=False)
    monkeypatch.setattr(
        main.app.state, "auth_service",
        AuthService(settings=main.settings, repository=None), raising=False,
    )
    client = TestClient(main.app)
    r = client.post("/tasks", json={"url": "https://x"})
    assert r.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_task_rate_limit.py -v`
Expected: FAIL — `ImportError: cannot import name 'RateLimitError'` / `count_since` missing.

- [ ] **Step 3a: Add `count_since` to the repository**

In `gateway/app/modules/task/repo.py`, update the sqlalchemy import and add the method:

```python
from sqlalchemy import func, select  # add func
```

```python
    def count_since(self, *, user_id: str, since) -> int:
        stmt = (
            select(func.count())
            .select_from(TaskRecordModel)
            .where(
                TaskRecordModel.user_id == user_id,
                TaskRecordModel.created_at >= since,
            )
        )
        try:
            with self._session_scope() as db:
                return int(db.execute(stmt).scalar_one() or 0)
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to count task records: {exc}") from exc
```

- [ ] **Step 3b: Add `RateLimitError` + enforcement to the service**

In `gateway/app/modules/task/service.py`, add `timedelta` to the datetime import:

```python
from datetime import datetime, timedelta, timezone
```

Add the error class next to `TaskExecutionError`:

```python
class RateLimitError(RuntimeError):
    """用户在限流窗口内超额:api 应映射为 429。"""
```

Extend `TaskService.__init__` signature and store the new fields:

```python
    def __init__(
        self,
        *,
        agents: dict[str, Any],
        repository: TaskRepository | None,
        resume_service: ResumeService | None,
        default_model: str,
        rate_limit_max: int = 0,
        rate_limit_window_seconds: int = 86400,
    ) -> None:
        self._agents = agents
        self._repository = repository
        self._resume_service = resume_service
        self._default_model = default_model
        self._rate_limit_max = rate_limit_max
        self._rate_limit_window_seconds = rate_limit_window_seconds
```

In `run`, right after the `agent is None` check and before `logger.info("task received...")`, add:

```python
        self._enforce_rate_limit(user_id)
```

Add the helper method (e.g. above `_resolve_cv_text`):

```python
    def _enforce_rate_limit(self, user_id: str | None) -> None:
        # 仅对已识别用户限流;匿名(自部署)不限。0 = 关闭。
        if user_id is None or self._repository is None or self._rate_limit_max <= 0:
            return
        since = datetime.now(timezone.utc) - timedelta(seconds=self._rate_limit_window_seconds)
        used = self._repository.count_since(user_id=user_id, since=since)
        if used >= self._rate_limit_max:
            raise RateLimitError(
                f"已达使用上限({self._rate_limit_max} 次 / {self._rate_limit_window_seconds}s),请稍后再试。"
            )
```

- [ ] **Step 3c: Map `RateLimitError` → 429 in the route**

In `gateway/app/modules/task/api.py`, update the service import and the `except` chain:

```python
from app.modules.task.service import RateLimitError, TaskExecutionError, TaskService
```

```python
    try:
        return service.run(task, user_id=user_id)
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 3d: Add config + wire into main.py**

In `gateway/app/config.py`, add to `Settings`:

```python
    # 单用户 /tasks 限流:窗口内最大次数,0=不限流(自部署默认);窗口秒数默认 1 天。
    task_rate_limit_max: int = 0
    task_rate_limit_window_seconds: int = 86400
```

In `from_env`:

```python
            task_rate_limit_max=_get_env_int("TASK_RATE_LIMIT_MAX", cls.task_rate_limit_max),
            task_rate_limit_window_seconds=_get_env_int(
                "TASK_RATE_LIMIT_WINDOW_SECONDS", cls.task_rate_limit_window_seconds
            ),
```

In `gateway/app/main.py`, extend the `TaskService(...)` construction in `lifespan`:

```python
    app.state.task_service = TaskService(
        agents=agents,
        repository=task_repository,
        resume_service=resume_service,
        default_model=settings.model,
        rate_limit_max=settings.task_rate_limit_max,
        rate_limit_window_seconds=settings.task_rate_limit_window_seconds,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_task_rate_limit.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/task/repo.py gateway/app/modules/task/service.py gateway/app/modules/task/api.py gateway/app/config.py gateway/app/main.py gateway/tests/test_task_rate_limit.py
git commit -m "feat(gateway): per-user /tasks rate limiting (429 over quota)"
```

---

### Task 8: Docs — `.env.example` + spec status

**Files:**
- Modify: `gateway/.env.example` (new env vars)
- Modify: `docs/superpowers/specs/2026-06-16-extension-auth-design.md` (mark gateway steps done)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add env vars**

Append a section to `gateway/.env.example`:

```bash
# ---- 扩展鉴权 / 限流（托管平台）-------------------------------------------
# /tasks 是否强制登录：托管平台 true（扩展须带 token / 网页带 cookie）；
# 开源自部署 false（匿名直连本地，token 可选）。
REQUIRE_AUTH=false
# 扩展 bearer token 有效期（秒），默认 30 天。
EXTENSION_TOKEN_TTL_SECONDS=2592000
# 单用户 /tasks 限流：窗口内最大次数，0=不限流（自部署默认）；窗口秒数默认 1 天。
TASK_RATE_LIMIT_MAX=0
TASK_RATE_LIMIT_WINDOW_SECONDS=86400
```

- [ ] **Step 2: Tick the gateway checkboxes in the spec**

In `docs/superpowers/specs/2026-06-16-extension-auth-design.md`, under "## 实施步骤", change the completed gateway items from `- [ ]` to `- [x]`:
- `auth_tokens` 表 + model/repo
- `POST /auth/extension-token`
- `GET`/`DELETE /auth/extension-tokens`
- `resolve_user_id`
- `/tasks` 接入 + `REQUIRE_AUTH`
- 输入封顶 + 限流

Leave the frontend / extension / README items unchecked.

- [ ] **Step 3: Full suite + commit**

Run the whole gateway suite to confirm nothing regressed:

Run: `cd gateway && uv run pytest -q`
Expected: all tests pass.

```bash
git add gateway/.env.example docs/superpowers/specs/2026-06-16-extension-auth-design.md
git commit -m "docs(gateway): env vars + spec status for extension auth"
```

---

## Self-Review

**Spec coverage:**
- `auth_tokens` table (DB opaque, sha256, label, last_used, expires, revoked) → Task 1 ✅
- `POST /auth/extension-token` → Task 3 ✅
- `GET`/`DELETE /auth/extension-tokens` (解绑端点 v1) → Task 3 ✅
- `resolve_user_id` (bearer-first, cookie fallback, touch last_used) → Task 2 (resolve) + Task 4 (resolver) ✅
- `/tasks` bearer + `REQUIRE_AUTH` matrix → Task 5 ✅
- Input caps → Task 6 ✅
- Per-user rate limit on `task_records` (429) → Task 7 ✅
- Store sha256 not plaintext → Task 2 ✅; never log token → no logging of token added anywhere ✅
- env vars + schema sql → Tasks 1, 8 ✅
- Frontend card / extension messaging / README updates → out of scope (separate plans), as stated.

**Placeholder scan:** No TBD/TODO; every code step has complete code and exact run commands. ✅

**Type consistency:** `resolve(token)->str|None`, `issue(*,user_id,label)->ExtensionTokenIssued`, `count_since(*,user_id,since)->int`, `revoke(*,user_id,token_id)->bool`, `TaskService(...rate_limit_max,rate_limit_window_seconds)` used identically across tasks. `ExtensionTokenInfo` field set matches model columns. ✅

**tz handling:** `_as_utc` covers SQLite naive read-back for expiry; `count_since`/`since` both UTC so SQLite string comparison is consistent. ✅
