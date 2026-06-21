import pytest

from app.agents.base import OpenAIChatAgent
from app.agents.model_router import ModelRouter, ModelTier
from app.modules.task.schema import TaskCreate


# --- ModelRouter.pick: 选「容得下的最小层」,超上限走 default ----------------

def make_router() -> ModelRouter:
    return ModelRouter.from_json(
        '{'
        '"6000":   {"url": "https://a", "key": "ka", "model": "small"},'
        '"31000":  {"url": "https://b", "key": "kb", "model": "mid"},'
        '"default":{"url": "https://c", "key": "kc", "model": "big"}'
        '}'
    )


def test_pick_smallest_tier_that_fits():
    router = make_router()
    assert router.pick(2000).model == "small"
    assert router.pick(6000).model == "small"  # 边界:<= 阈值算容得下
    assert router.pick(6001).model == "mid"
    assert router.pick(31000).model == "mid"
    assert router.pick(31001).model == "big"  # 超过所有阈值 -> default
    assert router.pick(500000).model == "big"


def test_default_only_router_always_picks_default():
    router = ModelRouter.from_json('{"default": {"url": "u", "key": "k", "model": "only"}}')
    assert router.pick(0).model == "only"
    assert router.pick(10**6).model == "only"
    assert router.default_model == "only"


def test_default_model_property():
    assert make_router().default_model == "big"


# --- from_json 校验 ----------------------------------------------------------

def test_from_json_requires_default():
    with pytest.raises(ValueError, match="default"):
        ModelRouter.from_json('{"6000": {"url": "u", "key": "k", "model": "m"}}')


def test_from_json_rejects_non_object():
    with pytest.raises(ValueError):
        ModelRouter.from_json('[1, 2, 3]')


def test_from_json_rejects_invalid_json():
    with pytest.raises(ValueError):
        ModelRouter.from_json('{not json}')


def test_from_json_rejects_non_integer_threshold():
    with pytest.raises(ValueError, match="threshold|阈值"):
        ModelRouter.from_json(
            '{"fast": {"url": "u", "key": "k", "model": "m"},'
            ' "default": {"url": "u", "key": "k", "model": "d"}}'
        )


def test_from_json_rejects_non_positive_threshold():
    with pytest.raises(ValueError):
        ModelRouter.from_json(
            '{"0": {"url": "u", "key": "k", "model": "m"},'
            ' "default": {"url": "u", "key": "k", "model": "d"}}'
        )


def test_from_json_requires_model_field():
    with pytest.raises(ValueError, match="model"):
        ModelRouter.from_json('{"default": {"url": "u", "key": "k"}}')


def test_from_json_allows_empty_url_and_key():
    router = ModelRouter.from_json('{"default": {"model": "m"}}')
    tier = router.pick(0)
    assert tier.model == "m"
    assert tier.url == ""
    assert tier.key == ""


# --- agent.pick_model 经 router 生效 ----------------------------------------

class DummyAgent(OpenAIChatAgent):
    name = "dummy"

    def build_prompt(self, task: TaskCreate) -> str:
        return task.page_text


def test_agent_pick_model_routes_by_length():
    router = ModelRouter.from_json(
        '{"10": {"url": "u", "key": "k", "model": "fast"},'
        ' "default": {"url": "u", "key": "k", "model": "quality"}}'
    )
    agent = DummyAgent(router=router)
    assert agent.pick_model("x" * 10) == "fast"
    assert agent.pick_model("x" * 11) == "quality"


def test_agent_without_router_uses_fixed_model():
    agent = DummyAgent(model="quality-model")
    assert agent.pick_model("x" * 100000) == "quality-model"


def test_run_uses_routed_tier_model():
    captured = {}

    class CapturingAgent(DummyAgent):
        def complete(self, system: str, user: str, tier: ModelTier) -> str:
            captured["model"] = tier.model
            return "ok"

    router = ModelRouter.from_json(
        '{"10": {"url": "u", "key": "k", "model": "fast"},'
        ' "default": {"url": "u", "key": "k", "model": "quality"}}'
    )
    agent = CapturingAgent(router=router)
    task = TaskCreate(url="https://example.com", page_text="x" * 50)
    assert agent.run(task) == "ok"
    assert captured["model"] == "quality"


# --- 同厂多层共用一个 client ------------------------------------------------

def test_clients_cached_per_url_key(monkeypatch):
    built: list[tuple] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            built.append((kwargs.get("base_url", ""), kwargs.get("api_key", "")))

    monkeypatch.setattr("app.agents.base.OpenAI", FakeOpenAI)

    router = ModelRouter.from_json(
        '{"10": {"url": "https://same", "key": "k", "model": "fast"},'
        ' "20": {"url": "https://same", "key": "k", "model": "mid"},'
        ' "default": {"url": "https://other", "key": "k2", "model": "big"}}'
    )
    agent = DummyAgent(router=router)
    # 两个同 (url,key) 的层只构建一次 client;不同的另构建一个。
    agent._client_for(router.pick(5))
    agent._client_for(router.pick(15))
    agent._client_for(router.pick(999))
    assert len(built) == 2
    assert ("https://same", "k") in built
    assert ("https://other", "k2") in built
