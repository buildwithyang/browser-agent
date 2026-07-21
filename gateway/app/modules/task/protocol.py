"""Stable version identifiers and the task wire-protocol gate."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# This version is a wire-contract integer, independent from manifest.json releases.
CURRENT_EXTENSION_PROTOCOL_VERSION = 4
EXTENSION_PROTOCOL_HEADER = "X-Agent-Bridge-Protocol-Version"
DEFAULT_EXTENSION_UPDATE_URL = (
    "https://chromewebstore.google.com/detail/agent-bridge/"
    "cmajoaedbjinocbfdkebaedkdbkhbhai"
)

_VERSIONED_TASK_PATHS = frozenset({"/tasks/quick-insight", "/tasks/workspace"})
_LEGACY_TASK_PATH = "/tasks"
_PROTOCOL_HEADER_BYTES = EXTENSION_PROTOCOL_HEADER.lower().encode("ascii")
_MAX_PROTOCOL_VALUE_BYTES = 32


def upgrade_required_response(update_url: str) -> JSONResponse:
    """Build the stable direct response used by every unsupported task client."""

    return JSONResponse(
        status_code=426,
        content={
            "code": "extension_update_required",
            "message": "Extension update required",
            "required_protocol_version": CURRENT_EXTENSION_PROTOCOL_VERSION,
            "update_url": update_url,
        },
        headers={
            EXTENSION_PROTOCOL_HEADER: str(CURRENT_EXTENSION_PROTOCOL_VERSION),
            "Upgrade": f"Agent-Bridge/{CURRENT_EXTENSION_PROTOCOL_VERSION}",
        },
    )


def _raw_protocol_headers(scope: Scope) -> list[bytes]:
    """Return every raw protocol Header value without consuming the request body."""

    return [
        value
        for name, value in scope.get("headers", [])
        if name.lower() == _PROTOCOL_HEADER_BYTES
    ]


def _is_current_protocol(raw_value: bytes | None) -> bool:
    """Accept only a bounded positive integer equal to the current wire version."""

    if raw_value is None or not raw_value.strip():
        return False
    stripped = raw_value.strip()
    if len(stripped) > _MAX_PROTOCOL_VALUE_BYTES:
        return False
    try:
        parsed = int(stripped)
    except (ValueError, OverflowError):
        return False
    return parsed > 0 and parsed == CURRENT_EXTENSION_PROTOCOL_VERSION


def _replace_protocol_header(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Replace any inner protocol marker with one deterministic current value."""

    filtered = [(name, value) for name, value in headers if name.lower() != _PROTOCOL_HEADER_BYTES]
    filtered.append(
        (_PROTOCOL_HEADER_BYTES, str(CURRENT_EXTENSION_PROTOCOL_VERSION).encode("ascii"))
    )
    return filtered


class TaskProtocolMiddleware:
    """Gate extension task POSTs before session, routing, auth, and body parsing."""

    def __init__(self, app: ASGIApp, *, update_url: str) -> None:
        """Wrap one ASGI app with the configured Extension update destination."""

        self.app = app
        self.update_url = update_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject unsupported task clients or tag every accepted inner response."""

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if method == "OPTIONS" or method != "POST":
            await self.app(scope, receive, send)
            return

        if path == _LEGACY_TASK_PATH:
            await upgrade_required_response(self.update_url)(scope, receive, send)
            return

        if path not in _VERSIONED_TASK_PATHS:
            await self.app(scope, receive, send)
            return

        protocol_values = _raw_protocol_headers(scope)
        if len(protocol_values) != 1 or not _is_current_protocol(protocol_values[0]):
            await upgrade_required_response(self.update_url)(scope, receive, send)
            return

        async def send_with_protocol(message: Message) -> None:
            """Append the current protocol marker to every accepted HTTP response."""

            if message["type"] == "http.response.start":
                message["headers"] = _replace_protocol_header(
                    list(message.get("headers", []))
                )
            await send(message)

        await self.app(scope, receive, send_with_protocol)
