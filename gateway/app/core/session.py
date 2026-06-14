from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CookieSessionMiddleware:
    """Signed-cookie session, populating ``scope["session"]`` (read via ``request.session``).

    The cookie is signed with ``AUTH_SESSION_SECRET`` to prevent tampering; it is
    NOT encrypted, so never store sensitive plaintext in the session.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        session_cookie: str = "agent_bridge_session",
        max_age: int = 14 * 24 * 60 * 60,
        same_site: str = "lax",
        https_only: bool = False,
    ) -> None:
        self.app = app
        self.secret_key = secret_key.encode("utf-8")
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.security_flags = "httponly; samesite=" + same_site
        if https_only:
            self.security_flags += "; secure"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        initial_session = self._load_session(connection.cookies.get(self.session_cookie))
        scope["session"] = dict(initial_session)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                session = scope.get("session", {})
                if session:
                    headers.append("Set-Cookie", self._build_cookie(dict(session)))
                elif initial_session:
                    headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}=null; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; "
                        f"{self.security_flags}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _load_session(self, cookie_value: str | None) -> dict[str, Any]:
        if not cookie_value or "." not in cookie_value:
            return {}

        payload, signature = cookie_value.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(payload)):
            return {}
        try:
            padded = payload + "=" * (-len(payload) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _build_cookie(self, session: dict[str, Any]) -> str:
        raw = json.dumps(session, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        signature = self._sign(payload)
        return (
            f"{self.session_cookie}={payload}.{signature}; path=/; max-age={self.max_age}; "
            f"{self.security_flags}"
        )

    def _sign(self, payload: str) -> str:
        digest = hmac.new(self.secret_key, payload.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
