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
        return ExtensionTokenIssued(token=token, user_id=user_id, expires_at=expires_at)

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

    def revoke_all_for_user(self, user_id: str) -> int:
        # 登出联动：吊销该用户全部扩展 token，使其 resolve() 立即失效。
        if self._repository is None:
            return 0
        return self._repository.revoke_all_for_user(user_id)
