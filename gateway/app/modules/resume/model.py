from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.sql_types import UUIDHexString

# parse_status 取值约定：0 待解析 / 1 解析完成可用 / 2 解析失败。
PARSE_PENDING = 0
PARSE_READY = 1
PARSE_FAILED = 2


class ResumeModel(Base):
    __tablename__ = "resume_resumes"
    __table_args__ = (
        Index("idx_resume_user_created_at", "user_id", "created_at"),
        Index("idx_resume_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(UUIDHexString(), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUIDHexString(), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # 解析出的简历纯文本，供 job_match 使用。
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    parse_status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    parse_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 当前生效的简历（job_match 用它），每个用户至多一条为 True。
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
