from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.modules.task.model import TaskRecordModel
from app.modules.task.schema import TaskRecordData


class TaskRepository:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session_scope(self) -> Iterator[OrmSession]:
        db = self._session_factory()
        try:
            yield db
        finally:
            db.close()

    def append(self, record: TaskRecordData) -> None:
        try:
            with self._session_scope() as db:
                db.add(
                    TaskRecordModel(
                        id=record.id,
                        user_id=record.user_id,
                        agent=record.agent.value,
                        lang=record.lang,
                        model=record.model,
                        status=record.status,
                        input_chars=record.input_chars,
                        result_chars=record.result_chars,
                        duration_ms=record.duration_ms,
                        error=record.error or None,
                        # 任务明细始终随记录持久化；缺少上下文时字段可为 None。
                        url=record.url,
                        title=record.title,
                        prompt=record.prompt,
                        page_text=record.page_text,
                        result=record.result,
                    )
                )
                db.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to persist task record: {exc}") from exc

    def list_recent(self, *, user_id: str, limit: int = 50) -> list[TaskRecordData]:
        stmt = (
            select(TaskRecordModel)
            .where(TaskRecordModel.user_id == user_id)
            .order_by(TaskRecordModel.created_at.desc())
            .limit(limit)
        )
        try:
            with self._session_scope() as db:
                rows = db.execute(stmt).scalars().all()
                return [self._to_data(model) for model in rows]
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to list task records: {exc}") from exc

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

    @staticmethod
    def _to_data(model: TaskRecordModel) -> TaskRecordData:
        return TaskRecordData(
            id=model.id,
            user_id=model.user_id,
            agent=model.agent,
            lang=model.lang,
            model=model.model,
            status=model.status,
            input_chars=int(model.input_chars or 0),
            result_chars=int(model.result_chars or 0),
            duration_ms=model.duration_ms,
            error=model.error or "",
            created_at=model.created_at,
        )
