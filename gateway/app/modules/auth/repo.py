from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.modules.auth.model import UserModel


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
