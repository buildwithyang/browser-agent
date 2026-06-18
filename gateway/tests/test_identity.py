from types import SimpleNamespace

from app.modules.auth.identity import resolve_user_id


class _TokenSvc:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, token):
        return self._mapping.get(token)


class _AuthSvc:
    def __init__(self, user):
        self._user = user

    def get_current_user(self, session):
        return self._user


def _req(*, headers=None, session=None, token_service=None, auth_service=None):
    state = SimpleNamespace(
        extension_token_service=token_service, auth_service=auth_service
    )
    return SimpleNamespace(app=SimpleNamespace(state=state), headers=headers or {}, session=session or {})


def test_bearer_takes_precedence():
    req = _req(headers={"Authorization": "Bearer good"}, token_service=_TokenSvc({"good": "U1"}))
    assert resolve_user_id(req) == "U1"


def test_falls_back_to_cookie_when_no_bearer():
    req = _req(token_service=_TokenSvc({}), auth_service=_AuthSvc(SimpleNamespace(user_id="U2")))
    assert resolve_user_id(req) == "U2"


def test_invalid_bearer_then_no_cookie_returns_none():
    req = _req(
        headers={"Authorization": "Bearer bad"},
        token_service=_TokenSvc({}),
        auth_service=_AuthSvc(None),
    )
    assert resolve_user_id(req) is None


def test_no_services_returns_none():
    assert resolve_user_id(_req()) is None
