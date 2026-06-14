from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session as OrmSession, sessionmaker

from app.config import Settings

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool
    from sqlalchemy.engine import Engine


class Base(DeclarativeBase):
    pass


@dataclass(slots=True)
class DatabaseResources:
    pool: "ConnectionPool | None" = None
    engine: "Engine | None" = None
    session_factory: sessionmaker[OrmSession] | None = None


def to_sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def create_database_resources(settings: Settings) -> DatabaseResources:
    if not settings.database_url:
        return DatabaseResources()

    database_url = settings.database_url
    sqlalchemy_database_url = to_sqlalchemy_database_url(database_url)

    connect_pool = None
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}

    if sqlalchemy_database_url.startswith("sqlite:///"):
        sqlite_path = sqlalchemy_database_url[len("sqlite:///") :]
        if sqlite_path and sqlite_path != ":memory:" and not sqlite_path.startswith("file:"):
            Path(sqlite_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "psycopg_pool is required for PostgreSQL. Run: uv sync --extra postgres"
            ) from exc

        connect_pool = ConnectionPool(
            conninfo=database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            timeout=settings.db_pool_timeout,
            open=False,
        )
        connect_pool.open(wait=True)

    engine = create_engine(sqlalchemy_database_url, **engine_kwargs)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    # 导入所有 model，确保 create_all 能看到全部表定义。
    import app.modules.auth.model  # noqa: F401
    import app.modules.resume.model  # noqa: F401
    import app.modules.task.model  # noqa: F401

    Base.metadata.create_all(engine)
    return DatabaseResources(
        pool=connect_pool,
        engine=engine,
        session_factory=session_factory,
    )


def close_database_resources(resources: DatabaseResources) -> None:
    if resources.pool is not None:
        resources.pool.close()
    if resources.engine is not None:
        resources.engine.dispose()
