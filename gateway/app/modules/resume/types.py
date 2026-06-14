from __future__ import annotations

from datetime import timedelta
from typing import Protocol


class StorageProvider(Protocol):
    """对象存储抽象：业务层只通过它生成预签名 URL 和回源下载，不感知云厂商 SDK。"""

    def generate_presigned_put_url(
        self,
        object_key: str,
        content_type: str,
        expires: timedelta,
    ) -> str:
        ...

    def generate_presigned_get_url(
        self,
        object_key: str,
        expires: timedelta,
    ) -> str:
        ...

    def download_bytes(self, object_key: str) -> bytes:
        """服务端回源下载对象原始字节（用于解析简历 PDF 文本）。"""
        ...

    def delete_object(self, object_key: str) -> None:
        ...
