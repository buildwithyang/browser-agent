from __future__ import annotations

_BEARER_PREFIX = "Bearer "


def resolve_user_id(request) -> str | None:
    """解析当前请求的 user_id：先 Authorization: Bearer，再回退 session cookie。

    扩展跨站 fetch 发不出 cookie，必须走 bearer；同源 Web 调用走 cookie。
    """
    token_service = getattr(request.app.state, "extension_token_service", None)
    if token_service is not None:
        header = request.headers.get("Authorization") or ""
        if header.startswith(_BEARER_PREFIX):
            token = header[len(_BEARER_PREFIX):].strip()
            if token:
                user_id = token_service.resolve(token)
                if user_id is not None:
                    return user_id

    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is not None:
        user = auth_service.get_current_user(request.session)
        if user is not None:
            return user.user_id

    return None
