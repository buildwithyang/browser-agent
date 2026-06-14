from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.sql_types import UUIDHexString


class TaskRecordModel(Base):
    """任务记录（metrics-only）。

    刻意不存 prompt / 结果文本 / 页面正文 / URL：这些是用户隐私(简历、浏览内容)。
    只保留运营指标，用于用量统计与后续按用户计费 / 限流。
    """

    __tablename__ = "task_records"
    __table_args__ = (
        Index("idx_task_records_user_created_at", "user_id", "created_at"),
        Index("idx_task_records_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUIDHexString(), primary_key=True)
    # 匿名扩展调用没有用户，可空。
    user_id: Mapped[str | None] = mapped_column(UUIDHexString(), nullable=True)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'auto'"))
    model: Mapped[str] = mapped_column(String(128), nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    result_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
