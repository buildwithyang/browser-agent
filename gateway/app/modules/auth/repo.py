from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.modules.auth.model import ExtensionTokenModel, UserModel


class UserRepository:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    def get_user_by_id(self, user_id: str) -> UserModel | None:
        stmt = select(UserModel).where(UserModel.user_id == user_id).limit(1)
        try:
            with self._session_factory() as db:
                return db.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to query user by id: {exc}") from exc

    def upsert_oauth_user(
        self,
        *,
        provider: str,
        provider_subject: str,
        username: str | None,
        display_name: str | None,
        email: str | None,
        avatar_url: str | None,
    ) -> UserModel:
        stmt = (
            select(UserModel)
            .where(
                UserModel.provider == provider,
                UserModel.provider_subject == provider_subject,
            )
            .limit(1)
        )
        try:
            with self._session_factory() as db:
                user = db.execute(stmt).scalar_one_or_none()
                if user is None:
                    user = UserModel(
                        user_id=uuid.uuid4().hex,
                        provider=provider,
                        provider_subject=provider_subject,
                    )
                    db.add(user)

                user.username = username
                user.display_name = display_name
                user.email = email
                user.avatar_url = avatar_url
                db.commit()
                db.refresh(user)
                return user
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Failed to upsert OAuth user: {exc}") from exc


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
        stmt = (
            select(ExtensionTokenModel)
            .where(ExtensionTokenModel.token_hash == token_hash)
            .limit(1)
        )
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
