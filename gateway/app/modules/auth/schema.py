from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "successful"
    data: T


class AuthUser(BaseModel):
    user_id: str
    provider: str
    provider_subject: str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    updated_at: datetime


class AuthMeData(BaseModel):
    user: AuthUser | None = None


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
