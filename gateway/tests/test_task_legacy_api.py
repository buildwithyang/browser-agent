"""Defensive legacy `/tasks` upgrade-shim tests."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.modules.task.protocol import DEFAULT_EXTENSION_UPDATE_URL

EXPECTED_BODY = {
    "code": "extension_update_required",
    "message": "Extension update required",
    "required_protocol_version": 4,
    "update_url": DEFAULT_EXTENSION_UPDATE_URL,
}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"not-json", id="malformed"),
        pytest.param(b"x" * 500_000, id="oversized"),
        pytest.param(b'{"url":"https://example.com"}', id="old-shape"),
    ],
)
def test_legacy_tasks_always_returns_the_same_upgrade_response(body: bytes) -> None:
    """Ignore every old body shape and return one stable direct 426 contract."""

    response = TestClient(main.app).post("/tasks", content=body)

    assert response.status_code == 426
    assert response.json() == EXPECTED_BODY
    assert response.headers["X-Agent-Bridge-Protocol-Version"] == "4"
    assert response.headers["Upgrade"] == "Agent-Bridge/4"
