from __future__ import annotations

import io
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from pypdf import PdfReader

from app.config import Settings
from app.modules.resume.model import PARSE_FAILED, PARSE_PENDING, PARSE_READY
from app.modules.resume.repo import ResumeRepository
from app.modules.resume.schema import ResumeData
from app.modules.resume.types import StorageProvider

logger = logging.getLogger("agent_bridge")

# 简历文本入库上限，避免超长 PDF 撑爆数据库与后续 prompt。
MAX_RESUME_TEXT_CHARS = 20000
CATEGORY = "resume"


class ResumeService:
    """简历业务层：预签名直传 + 服务端回源解析 + 按用户管理生效简历。"""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageProvider,
        repository: ResumeRepository | None,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._repository = repository

    def _require_repo(self) -> ResumeRepository:
        if self._repository is None:
            raise RuntimeError(
                "Resume repository is not configured. Set DATABASE_URL to enable persistence."
            )
        return self._repository

    def generate_object_key(self, *, user_id: str, filename: str) -> str:
        ext = Path(filename).suffix.lower() or ".pdf"
        return f"{CATEGORY}/{user_id}/{uuid.uuid4().hex}{ext}"

    def generate_upload_url(self, *, object_key: str, content_type: str) -> str:
        return self._storage.generate_presigned_put_url(
            object_key=object_key,
            content_type=content_type,
            expires=timedelta(minutes=10),
        )

    def build_asset_url(self, object_key: str) -> str:
        base = self._settings.asset_base_url.rstrip("/")
        return f"{base}/{object_key}"

    def complete_upload(
        self,
        *,
        user_id: str,
        object_key: str,
        filename: str | None,
        content_type: str | None,
        file_size: int | None,
        etag: str | None,
    ) -> ResumeData:
        repo = self._require_repo()

        # object_key 必须落在该用户的前缀下，杜绝越权写他人简历。
        expected_prefix = f"{CATEGORY}/{user_id}/"
        if not object_key.startswith(expected_prefix):
            raise ValueError("object_key does not belong to the current user")
        if file_size is not None and file_size > self._settings.resume_max_bytes:
            raise ValueError("resume file exceeds the size limit")

        resume_id = uuid.uuid4().hex
        repo.create(
            resume_id=resume_id,
            user_id=user_id,
            object_key=object_key,
            filename=filename or Path(object_key).name,
            content_type=content_type,
            file_size=file_size,
            etag=etag,
            storage_provider=self._settings.storage_provider,
            parse_status=PARSE_PENDING,
        )

        # 回源下载 + 解析文本；失败不阻断上传记录，标记为解析失败供前端提示。
        extracted_text = ""
        parse_status = PARSE_READY
        parse_error: str | None = None
        try:
            raw = self._storage.download_bytes(object_key)
            extracted_text = self._extract_text(raw)[:MAX_RESUME_TEXT_CHARS]
            if not extracted_text.strip():
                parse_status = PARSE_FAILED
                parse_error = "未能从文件中提取到文本（可能是扫描版 PDF）。"
        except Exception as exc:
            parse_status = PARSE_FAILED
            parse_error = str(exc)[:512]
            logger.warning("resume parse failed resume_id=%s err=%s", resume_id, exc)

        repo.set_parse_result(
            resume_id=resume_id,
            user_id=user_id,
            extracted_text=extracted_text or None,
            text_chars=len(extracted_text),
            parse_status=parse_status,
            parse_error=parse_error,
        )

        # 解析成功的简历自动设为生效，让 job_match 立即用上最新简历。
        if parse_status == PARSE_READY:
            repo.set_active(resume_id=resume_id, user_id=user_id)

        detail = repo.get_for_user(resume_id=resume_id, user_id=user_id)
        if detail is None:
            raise RuntimeError("resume disappeared right after creation")
        return detail

    def list_resumes(self, *, user_id: str) -> list[ResumeData]:
        return self._require_repo().list_by_user(user_id=user_id)

    def activate(self, *, user_id: str, resume_id: str) -> ResumeData:
        repo = self._require_repo()
        detail = repo.get_for_user(resume_id=resume_id, user_id=user_id)
        if detail is None:
            raise ValueError("resume not found")
        if detail.parse_status != PARSE_READY:
            raise ValueError("resume is not ready to be activated")
        repo.set_active(resume_id=resume_id, user_id=user_id)
        refreshed = repo.get_for_user(resume_id=resume_id, user_id=user_id)
        return refreshed or detail

    def delete(self, *, user_id: str, resume_id: str) -> None:
        repo = self._require_repo()
        object_key = repo.get_object_key(resume_id=resume_id, user_id=user_id)
        if object_key is None:
            raise ValueError("resume not found")
        if not repo.delete(resume_id=resume_id, user_id=user_id):
            raise ValueError("resume not found")
        # 先删库再尽力删对象；对象删除失败不影响用户视角。
        try:
            self._storage.delete_object(object_key)
        except Exception as exc:
            logger.warning("resume object delete failed key=%s err=%s", object_key, exc)

    def active_resume_text(self, *, user_id: str) -> str | None:
        return self._require_repo().active_resume_text(user_id=user_id)

    @staticmethod
    def _extract_text(data: bytes) -> str:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
