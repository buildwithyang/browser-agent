from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

import alibabacloud_oss_v2 as oss

from app.config import Settings
from app.modules.resume.types import StorageProvider


class FakeStorageProvider:
    """本地联调用：不真正存储，预签名 URL 指向占位 host，回源下载不可用。"""

    def generate_presigned_put_url(
        self,
        object_key: str,
        content_type: str,
        expires: timedelta,
    ) -> str:
        params = urlencode(
            {
                "object_key": object_key,
                "content_type": content_type,
                "expires": int(expires.total_seconds()),
            }
        )
        return f"http://fake-storage/upload?{params}"

    def generate_presigned_get_url(self, object_key: str, expires: timedelta) -> str:
        return f"http://fake-storage/object/{object_key}?expires={int(expires.total_seconds())}"

    def download_bytes(self, object_key: str) -> bytes:
        raise RuntimeError(
            "FakeStorageProvider 不支持回源下载，无法解析简历文本。请配置 STORAGE_PROVIDER=oss。"
        )

    def delete_object(self, object_key: str) -> None:
        # fake 没有真实对象，删除是 no-op。
        return None


class OSSStorageProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.oss_bucket:
            raise ValueError("OSS_BUCKET is required when STORAGE_PROVIDER=oss")
        if not settings.oss_access_key_id:
            raise ValueError("OSS_ACCESS_KEY_ID is required when STORAGE_PROVIDER=oss")
        if not settings.oss_access_key_secret:
            raise ValueError("OSS_ACCESS_KEY_SECRET is required when STORAGE_PROVIDER=oss")

        cfg = oss.config.load_default()
        cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
            settings.oss_access_key_id,
            settings.oss_access_key_secret,
        )
        cfg.region = settings.oss_region

        self._client = oss.Client(cfg)
        self._bucket = settings.oss_bucket

    def generate_presigned_put_url(
        self,
        object_key: str,
        content_type: str,
        expires: timedelta,
    ) -> str:
        pre = self._client.presign(
            oss.PutObjectRequest(
                bucket=self._bucket,
                key=object_key,
                content_type=content_type,
            ),
            expires=expires,
        )
        return pre.url or ""

    def generate_presigned_get_url(self, object_key: str, expires: timedelta) -> str:
        pre = self._client.presign(
            oss.GetObjectRequest(bucket=self._bucket, key=object_key),
            expires=expires,
        )
        return pre.url or ""

    def download_bytes(self, object_key: str) -> bytes:
        result = self._client.get_object(
            oss.GetObjectRequest(bucket=self._bucket, key=object_key)
        )
        body = result.body
        data = body.read() if hasattr(body, "read") else bytes(body or b"")
        return data

    def delete_object(self, object_key: str) -> None:
        self._client.delete_object(
            oss.DeleteObjectRequest(bucket=self._bucket, key=object_key)
        )


def create_storage_provider(settings: Settings) -> StorageProvider:
    if settings.storage_provider == "fake":
        return FakeStorageProvider()
    if settings.storage_provider == "oss":
        return OSSStorageProvider(settings)
    raise ValueError(f"Unsupported STORAGE_PROVIDER: {settings.storage_provider}")
