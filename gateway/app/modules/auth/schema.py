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
