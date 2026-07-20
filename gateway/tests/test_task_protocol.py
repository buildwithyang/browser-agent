"""Integration tests for the Extension task protocol gate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

from app import main
from app.core import CookieSessionMiddleware
from app.modules.task.protocol import (
    CURRENT_EXTENSION_PROTOCOL_VERSION,
    DEFAULT_EXTENSION_UPDATE_URL,
    EXTENSION_PROTOCOL_HEADER,
    upgrade_required_response,
    TaskProtocolMiddleware,
)
from app.modules.task.schema import (
    ActionId,
    Artifacts,
    ExecutionMeta,
    Insight,
    QuickInsightResponse,
    WorkspaceResponse,
    WorkspaceResultType,
    WorkspaceDescriptor,
)
from app.modules.task.service import RateLimitError, TaskExecutionError

PROTOCOL_VALUE = str(CURRENT_EXTENSION_PROTOCOL_VERSION)
PROTOCOL_HEADERS = {EXTENSION_PROTOCOL_HEADER: PROTOCOL_VALUE}
UPGRADE_JSON = {
    "code": "extension_update_required",
    "message": "Extension update required",
    "required_protocol_version": CURRENT_EXTENSION_PROTOCOL_VERSION,
    "update_url": DEFAULT_EXTENSION_UPDATE_URL,
}


class RecordingService:
    """Return stable endpoint responses while recording public service calls."""

    def __init__(self) -> None:
        """Start with an empty call log."""

        self.calls: list[tuple[str, object, str | None]] = []

    def quick_insight(self, task: Any, *, user_id: str | None) -> QuickInsightResponse:
        """Return a minimal successful Quick Insight response."""

        self.calls.append(("quick_insight", task, user_id))
        return QuickInsightResponse(
            request=task,
            insight=Insight(title="Summary"),
            workspace=WorkspaceDescriptor(
                resource_url="https://example.com/",
                default_action_id=ActionId.ASK_MORE,
            ),
            meta=ExecutionMeta(model="fake"),
        )

    def workspace(self, task: Any, *, user_id: str | None) -> WorkspaceResponse:
        """Return a minimal successful complete Workspace state."""

        self.calls.append(("workspace", task, user_id))
        return WorkspaceResponse(
            resource_url="https://example.com/",
            selected_action_id=ActionId.ASK_MORE,
            result_type=WorkspaceResultType.REPLY,
            histories=[],
            artifacts=Artifacts(cv=None, cover_letter=None),
            meta=ExecutionMeta(model="fake"),
        )


def _wire(monkeypatch: pytest.MonkeyPatch, service: object, *, require_auth: bool = False) -> None:
    """Install request-scoped test doubles without rebuilding the global app."""

    monkeypatch.setattr(main.app.state, "task_service", service, raising=False)
    monkeypatch.setattr(
        main.app.state,
        "settings",
        SimpleNamespace(require_auth=require_auth),
        raising=False,
    )


def _workspace_payload() -> dict[str, object]:
    """Build the minimum valid final Workspace request."""

    return {
        "trigger": "user_message",
        "url": "https://example.com",
        "resourceUrl": "https://example.com/",
        "actionId": "ask_more",
        "histories": [],
        "artifacts": {"cv": None, "cover_letter": None},
        "message": "What matters?",
    }


def _assert_upgrade_required(response: Any) -> None:
    """Assert the stable body and transport headers for one 426 response."""

    assert response.status_code == 426
    assert response.json() == UPGRADE_JSON
    assert response.headers[EXTENSION_PROTOCOL_HEADER] == PROTOCOL_VALUE
    assert response.headers["upgrade"] == "Agent-Bridge/2"


def test_upgrade_response_factory_uses_configured_update_url() -> None:
    """Keep deployment-specific update destinations in the shared 426 body."""

    response = upgrade_required_response("https://updates.example/extension")

    assert b'"update_url":"https://updates.example/extension"' in response.body


def test_middleware_execution_order_is_cors_protocol_session_router() -> None:
    """Keep the protocol gate outside session handling and inside CORS."""

    assert [item.cls for item in main.app.user_middleware[:3]] == [
        CORSMiddleware,
        TaskProtocolMiddleware,
        CookieSessionMiddleware,
    ]


@pytest.mark.parametrize("path", ["/tasks/quick-insight", "/tasks/workspace"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("not-an-integer", id="non-integer"),
        pytest.param("0", id="zero"),
        pytest.param("-1", id="negative"),
        pytest.param("1", id="older"),
        pytest.param("3", id="newer"),
        pytest.param("9" * 10_000, id="huge"),
    ],
)
def test_task_endpoints_reject_missing_malformed_and_unequal_protocol(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    value: str | None,
) -> None:
    """Reject every unsupported header form before body, auth, or service work."""

    service = RecordingService()
    _wire(monkeypatch, service, require_auth=True)
    headers = {} if value is None else {EXTENSION_PROTOCOL_HEADER: value}

    response = TestClient(main.app).post(path, content=b"{broken", headers=headers)

    _assert_upgrade_required(response)
    assert service.calls == []


@pytest.mark.parametrize(
    ("path", "payload", "operation"),
    [
        ("/tasks/quick-insight", {"url": "https://example.com"}, "quick_insight"),
        ("/tasks/workspace", _workspace_payload(), "workspace"),
    ],
)
def test_matching_protocol_reaches_service_and_marks_success_response(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, object],
    operation: str,
) -> None:
    """Pass version two to the router exactly once and tag successful JSON."""

    service = RecordingService()
    _wire(monkeypatch, service)

    response = TestClient(main.app).post(path, json=payload, headers=PROTOCOL_HEADERS)

    assert response.status_code == 200
    assert response.headers[EXTENSION_PROTOCOL_HEADER] == PROTOCOL_VALUE
    assert response.json()["protocol_version"] == CURRENT_EXTENSION_PROTOCOL_VERSION
    assert [call[0] for call in service.calls] == [operation]


@pytest.mark.parametrize(
    ("expected_status", "service"),
    [
        (429, SimpleNamespace(quick_insight=lambda *_args, **_kwargs: (_ for _ in ()).throw(RateLimitError("quota")))),
        (502, SimpleNamespace(quick_insight=lambda *_args, **_kwargs: (_ for _ in ()).throw(TaskExecutionError("upstream")))),
    ],
)
def test_matching_protocol_marks_mapped_service_errors(
    monkeypatch: pytest.MonkeyPatch,
    expected_status: int,
    service: object,
) -> None:
    """Tag mapped 429 and 502 responses produced inside the task API."""

    _wire(monkeypatch, service)

    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        json={"url": "https://example.com"},
        headers=PROTOCOL_HEADERS,
    )

    assert response.status_code == expected_status
    assert response.headers[EXTENSION_PROTOCOL_HEADER] == PROTOCOL_VALUE


def test_matching_protocol_marks_auth_validation_and_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tag inner 401, 422, and mapped 400 responses after protocol acceptance."""

    service = RecordingService()
    _wire(monkeypatch, service, require_auth=True)
    client = TestClient(main.app)
    unauthorized = client.post(
        "/tasks/quick-insight",
        json={"url": "https://example.com"},
        headers=PROTOCOL_HEADERS,
    )
    invalid_body = client.post(
        "/tasks/workspace",
        content=b"{broken",
        headers=PROTOCOL_HEADERS,
    )
    invalid_url_service = SimpleNamespace(
        quick_insight=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("url must be an absolute HTTP(S) URL")
        )
    )
    _wire(monkeypatch, invalid_url_service, require_auth=False)
    invalid_url = client.post(
        "/tasks/quick-insight",
        json={"url": "not-an-absolute-url"},
        headers=PROTOCOL_HEADERS,
    )

    assert [unauthorized.status_code, invalid_body.status_code, invalid_url.status_code] == [
        401,
        422,
        400,
    ]
    for response in (unauthorized, invalid_body, invalid_url):
        assert response.headers[EXTENSION_PROTOCOL_HEADER] == PROTOCOL_VALUE


def test_cors_preflight_bypasses_gate_and_advertises_protocol_header() -> None:
    """Let outer CORS answer OPTIONS and expose the version header to extensions."""

    response = TestClient(main.app).options(
        "/tasks/workspace",
        headers={
            "Origin": "chrome-extension://abcdefghijklmnop",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": EXTENSION_PROTOCOL_HEADER,
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert EXTENSION_PROTOCOL_HEADER.lower() in response.headers[
        "access-control-allow-headers"
    ].lower()


def test_actual_cors_response_exposes_protocol_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make the protocol response marker readable by browser JavaScript."""

    _wire(monkeypatch, RecordingService())
    response = TestClient(main.app).post(
        "/tasks/quick-insight",
        json={"url": "https://example.com"},
        headers={**PROTOCOL_HEADERS, "Origin": "chrome-extension://abcdefghijklmnop"},
    )

    assert response.status_code == 200
    assert EXTENSION_PROTOCOL_HEADER.lower() in response.headers[
        "access-control-expose-headers"
    ].lower()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"{broken", id="malformed"),
        pytest.param(b"x" * 500_000, id="oversized"),
        pytest.param(
            b'{"url":"https://example.com","agent":"browser_agent"}',
            id="old-shape",
        ),
    ],
)
def test_exact_legacy_tasks_path_returns_426_without_resolving_service(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    """Intercept exact legacy POST bytes before validation or dependency lookup."""

    service = RecordingService()
    _wire(monkeypatch, service, require_auth=True)
    response = TestClient(main.app).post("/tasks", content=body)

    _assert_upgrade_required(response)
    assert service.calls == []
