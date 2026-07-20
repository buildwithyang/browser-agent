from fastapi.testclient import TestClient

from app import main
from app.modules.task.schema import PAGE_TEXT_MAX_CHARS


def test_oversized_page_text_rejected():
    client = TestClient(main.app)
    r = client.post(
        "/tasks/quick-insight",
        headers={"X-Agent-Bridge-Protocol-Version": "2"},
        json={"url": "https://x", "pageText": "a" * (PAGE_TEXT_MAX_CHARS + 1)},
    )
    assert r.status_code == 422


def test_within_cap_accepted_by_validation():
    # 校验通过即可（无需真正执行 agent）：不应是 422。
    client = TestClient(main.app)
    r = client.post(
        "/tasks/quick-insight",
        headers={"X-Agent-Bridge-Protocol-Version": "2"},
        json={"url": "https://x", "pageText": "a" * 100},
    )
    assert r.status_code != 422
