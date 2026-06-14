from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.modules.resume.model import ResumeModel
from app.modules.resume.schema import ResumeData


class ResumeRepository:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session_scope(self) -> Iterator[OrmSession]:
        db = self._session_factory()
        try:
            yield db
        finally:
            db.close()

    def create(
        self,
        *,
        resume_id: str,
        user_id: str,
        object_key: str,
        filename: str | None,
        content_type: str | None,
        file_size: int | None,
        etag: str | None,
        storage_provider: str,
        parse_status: int,
    ) -> None:
        try:
            with self._session_scope() as db:
                db.add(
                    ResumeModel(
                        id=resume_id,
                        user_id=user_id,
                        object_key=object_key,
                        filename=filename,
                        content_type=content_type,
                        file_size=file_size,
                        etag=etag,
                        storage_provider=storage_provider,
                        parse_status=parse_status,
                    )
                )
                db.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to create resume record: {exc}") from exc

    def set_parse_result(
        self,
        *,
        resume_id: str,
        user_id: str,
        extracted_text: str | None,
        text_chars: int,
        parse_status: int,
        parse_error: str | None,
    ) -> None:
        try:
            with self._session_scope() as db:
                model = db.get(ResumeModel, resume_id)
                if model is None or model.user_id != user_id:
                    return
                model.extracted_text = extracted_text
                model.text_chars = text_chars
                model.parse_status = parse_status
                model.parse_error = parse_error
                db.commit()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to update resume parse result: {exc}") from exc

    def set_active(self, *, resume_id: str, user_id: str) -> bool:
        """把该用户的目标简历设为生效，其余取消生效；不存在/越权返回 False。"""
        try:
            with self._session_scope() as db:
                model = db.get(ResumeModel, resume_id)
                if model is None or model.user_id != user_id:
                    return False
                db.execute(
                    update(ResumeModel)
                    .where(ResumeModel.user_id == user_id)
                    .values(is_active=False)
                )
                model.is_active = True
                db.commit()
                return True
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to set active resume: {exc}") from exc

    def list_by_user(self, *, user_id: str, limit: int = 50) -> list[ResumeData]:
        stmt = (
            select(ResumeModel)
            .where(ResumeModel.user_id == user_id)
            .order_by(ResumeModel.created_at.desc())
            .limit(limit)
        )
        try:
            with self._session_scope() as db:
                rows = db.execute(stmt).scalars().all()
                return [self._to_data(model) for model in rows]
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to list resumes: {exc}") from exc

    def get_for_user(self, *, resume_id: str, user_id: str) -> ResumeData | None:
        try:
            with self._session_scope() as db:
                model = db.get(ResumeModel, resume_id)
                if model is None or model.user_id != user_id:
                    return None
                return self._to_data(model)
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to query resume: {exc}") from exc

    def get_object_key(self, *, resume_id: str, user_id: str) -> str | None:
        try:
            with self._session_scope() as db:
                model = db.get(ResumeModel, resume_id)
                if model is None or model.user_id != user_id:
                    return None
                return model.object_key
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to query resume object_key: {exc}") from exc

    def active_resume_text(self, *, user_id: str) -> str | None:
        stmt = (
            select(ResumeModel.extracted_text)
            .where(ResumeModel.user_id == user_id, ResumeModel.is_active.is_(True))
            .limit(1)
        )
        try:
            with self._session_scope() as db:
                return db.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to query active resume text: {exc}") from exc

    def delete(self, *, resume_id: str, user_id: str) -> bool:
        try:
            with self._session_scope() as db:
                model = db.get(ResumeModel, resume_id)
                if model is None or model.user_id != user_id:
                    return False
                db.delete(model)
                db.commit()
                return True
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to delete resume: {exc}") from exc

    @staticmethod
    def _to_data(model: ResumeModel) -> ResumeData:
        return ResumeData(
            id=model.id,
            filename=model.filename,
            content_type=model.content_type,
            file_size=model.file_size,
            text_chars=int(model.text_chars or 0),
            parse_status=int(model.parse_status),
            parse_error=model.parse_error,
            is_active=bool(model.is_active),
            created_at=model.created_at,
        )
