import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.resume.model  # noqa: F401  -- register table on Base.metadata
from app.core.db import Base
from app.modules.resume.model import PARSE_PENDING, PARSE_READY
from app.modules.resume.repo import ResumeRepository

USER_A = uuid.uuid4().hex
USER_B = uuid.uuid4().hex
R1 = uuid.uuid4().hex
R2 = uuid.uuid4().hex


def _make_repo(tmp_path) -> ResumeRepository:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'resume.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ResumeRepository(factory)


def _add(repo: ResumeRepository, *, resume_id: str, user_id: str) -> None:
    repo.create(
        resume_id=resume_id,
        user_id=user_id,
        object_key=f"resume/{user_id}/{resume_id}.pdf",
        filename="cv.pdf",
        content_type="application/pdf",
        file_size=1234,
        etag=None,
        storage_provider="fake",
        parse_status=PARSE_PENDING,
    )


def test_create_parse_and_active_text(tmp_path):
    repo = _make_repo(tmp_path)
    _add(repo, resume_id=R1, user_id=USER_A)

    repo.set_parse_result(
        resume_id=R1,
        user_id=USER_A,
        extracted_text="Senior Go engineer",
        text_chars=18,
        parse_status=PARSE_READY,
        parse_error=None,
    )
    repo.set_active(resume_id=R1, user_id=USER_A)

    assert repo.active_resume_text(user_id=USER_A) == "Senior Go engineer"
    items = repo.list_by_user(user_id=USER_A)
    assert len(items) == 1 and items[0].is_active is True and items[0].text_chars == 18


def test_set_active_is_exclusive_per_user(tmp_path):
    repo = _make_repo(tmp_path)
    _add(repo, resume_id=R1, user_id=USER_A)
    _add(repo, resume_id=R2, user_id=USER_A)

    repo.set_active(resume_id=R1, user_id=USER_A)
    repo.set_active(resume_id=R2, user_id=USER_A)

    actives = [r.id for r in repo.list_by_user(user_id=USER_A) if r.is_active]
    assert actives == [R2]


def test_cross_user_access_is_blocked(tmp_path):
    repo = _make_repo(tmp_path)
    _add(repo, resume_id=R1, user_id=USER_A)

    # 另一个用户既不能读、也不能改、也不能删别人的简历。
    assert repo.get_for_user(resume_id=R1, user_id=USER_B) is None
    assert repo.set_active(resume_id=R1, user_id=USER_B) is False
    assert repo.delete(resume_id=R1, user_id=USER_B) is False
    # 原主仍可正常删除。
    assert repo.delete(resume_id=R1, user_id=USER_A) is True
    assert repo.list_by_user(user_id=USER_A) == []
