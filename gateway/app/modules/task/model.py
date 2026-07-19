from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.sql_types import UUIDHexString


class TaskRecordModel(Base):
    """任务记录。

    Repository/DB 配置时持久化任务指标和明细字段(url/title/prompt/page_text/result)。
    明细字段可能包含用户隐私，调用方应按部署的数据保留策略处理。
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
    # 任务明细（含隐私；个别字段在失败或缺少页面上下文时可以为 NULL）。
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
