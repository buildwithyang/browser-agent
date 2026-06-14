from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "successful"
    data: T


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(default="application/pdf", min_length=1, max_length=128)


class UploadUrlResponseData(BaseModel):
    object_key: str
    upload_url: str
    asset_url: str


class CompleteUploadRequest(BaseModel):
    object_key: str = Field(..., min_length=1, max_length=1024)
    filename: str | None = Field(default=None, max_length=255)
    content_type: str | None = Field(default=None, max_length=128)
    file_size: int | None = Field(default=None, ge=0)
    etag: str | None = Field(default=None, max_length=128)

    @field_validator("object_key")
    @classmethod
    def normalize_object_key(cls, value: str) -> str:
        normalized = value.strip().lstrip("/")
        if not normalized:
            raise ValueError("object_key is required")
        return normalized


class ResumeData(BaseModel):
    """简历领域对象（不含原文，列表/详情通用）。"""

    id: str
    filename: str | None = None
    content_type: str | None = None
    file_size: int | None = None
    text_chars: int = 0
    parse_status: int
    parse_error: str | None = None
    is_active: bool = False
    created_at: datetime


class ResumeListResponseData(BaseModel):
    items: list[ResumeData]


class ResumeDetailResponseData(BaseModel):
    resume: ResumeData
