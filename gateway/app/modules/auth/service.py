from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.modules.auth.model import UserModel
from app.modules.auth.repo import UserRepository
from app.modules.auth.schema import AuthUser


class AuthService:
    SESSION_USER_ID_KEY = "auth_user_id"
    STATE_KEY = "auth_oauth_state"
    NONCE_KEY = "auth_oauth_nonce"
    CODE_VERIFIER_KEY = "auth_oauth_code_verifier"

    def __init__(self, *, settings: Settings, repository: UserRepository | None) -> None:
        self._settings = settings
        self._repository = repository

    def build_authorization_url(self, session: dict[str, Any]) -> str:
        self._require_config()

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        # state/code_verifier 先写入签名 session cookie；callback 时用它们防 CSRF 并完成 PKCE 校验。
        session[self.STATE_KEY] = state
        session[self.NONCE_KEY] = nonce
        session[self.CODE_VERIFIER_KEY] = code_verifier

        params = {
            "client_id": self._settings.casdoor_client_id,
            "response_type": "code",
            "redirect_uri": self._settings.casdoor_redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": self._build_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{self._casdoor_endpoint}/login/oauth/authorize?{urlencode(params)}"

    def complete_callback(self, *, session: dict[str, Any], code: str, state: str) -> AuthUser:
        self._require_config()
        if self._repository is None:
            raise RuntimeError("User repository is not initialized")

        expected_state = session.pop(self.STATE_KEY, None)
        code_verifier = session.pop(self.CODE_VERIFIER_KEY, None)
        session.pop(self.NONCE_KEY, None)
        # callback 必须带回同一个浏览器 cookie；host 混用会导致读不到 state 并报 invalid OAuth state。
        if not expected_state or not secrets.compare_digest(str(expected_state), state):
            raise ValueError("invalid OAuth state")
        if not code_verifier:
            raise ValueError("missing OAuth code verifier")

        token_data = self._exchange_code(code=code, code_verifier=str(code_verifier))
        userinfo = self._fetch_userinfo(token_data)
        user = self._repository.upsert_oauth_user(**self._map_userinfo(userinfo))
        session[self.SESSION_USER_ID_KEY] = user.user_id
        return self.to_auth_user(user)

    def get_current_user(self, session: dict[str, Any]) -> AuthUser | None:
        if self._repository is None:
            return None
        user_id = session.get(self.SESSION_USER_ID_KEY)
        if not isinstance(user_id, str) or not user_id:
            return None
        user = self._repository.get_user_by_id(user_id)
        if user is None:
            session.pop(self.SESSION_USER_ID_KEY, None)
            return None
        return self.to_auth_user(user)

    def logout(self, session: dict[str, Any]) -> None:
        session.clear()

    @staticmethod
    def to_auth_user(user: UserModel) -> AuthUser:
        return AuthUser(
            user_id=user.user_id,
            provider=user.provider,
            provider_subject=user.provider_subject,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            avatar_url=user.avatar_url,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @property
    def _casdoor_endpoint(self) -> str:
        return self._settings.casdoor_endpoint.rstrip("/")

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("CASDOOR_ENDPOINT", self._settings.casdoor_endpoint),
                ("CASDOOR_CLIENT_ID", self._settings.casdoor_client_id),
                ("CASDOOR_CLIENT_SECRET", self._settings.casdoor_client_secret),
                ("CASDOOR_REDIRECT_URI", self._settings.casdoor_redirect_uri),
            )
            if not value.strip()
        ]
        if missing:
            raise RuntimeError(f"Auth is not configured: missing {', '.join(missing)}")

    def _exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._settings.casdoor_client_id,
            "client_secret": self._settings.casdoor_client_secret,
            "code": code,
            # 换 token 时 redirect_uri 也要和授权请求中的值一致，否则 Casdoor 会拒绝这个 code。
            "redirect_uri": self._settings.casdoor_redirect_uri,
            "code_verifier": code_verifier,
        }
        with httpx.Client(timeout=self._settings.casdoor_http_timeout, trust_env=False) as client:
            response = client.post(
                f"{self._casdoor_endpoint}/api/login/oauth/access_token", data=payload
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Casdoor token exchange failed with status {response.status_code}")
        data = response.json()
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Casdoor token exchange did not return an access token")
        return data

    def _fetch_userinfo(self, token_data: dict[str, Any]) -> dict[str, Any]:
        access_token = str(token_data["access_token"])
        with httpx.Client(timeout=self._settings.casdoor_http_timeout, trust_env=False) as client:
            response = client.get(
                f"{self._casdoor_endpoint}/api/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Casdoor userinfo request failed with status {response.status_code}")
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            raise RuntimeError("Casdoor userinfo response is not an object")
        return data

    @staticmethod
    def _map_userinfo(userinfo: dict[str, Any]) -> dict[str, str | None]:
        subject = _get_first_string(userinfo, "sub", "id", "name")
        if not subject:
            raise RuntimeError("Casdoor userinfo response is missing subject")

        return {
            "provider": "casdoor",
            "provider_subject": subject,
            "username": _get_first_string(userinfo, "name", "preferred_username"),
            "display_name": _get_first_string(userinfo, "displayName", "display_name", "name"),
            "email": _get_first_string(userinfo, "email"),
            "avatar_url": _get_first_string(userinfo, "avatar", "picture", "permanentAvatar"),
        }

    @staticmethod
    def _build_code_challenge(code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _get_first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
