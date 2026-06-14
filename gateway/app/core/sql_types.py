from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class UUIDHexString(TypeDecorator[str]):
    """Store UUIDs as their 32-char hex string, portable across SQLite/PostgreSQL."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value.hex

        normalized = str(value).strip()
        if not normalized:
            return None
        return uuid.UUID(normalized).hex

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(value)
