from app.agents.base import OpenAIChatAgent
from app.modules.task.schema import TaskCreate


class DummyAgent(OpenAIChatAgent):
    name = "dummy"

    def build_prompt(self, task: TaskCreate) -> str:
        return task.page_text


def test_long_input_routes_to_model_long():
    agent = DummyAgent(model="quality-model", model_long="fast-model", route_threshold_chars=10)
    assert agent.pick_model("x" * 10) == "quality-model"
    assert agent.pick_model("x" * 11) == "fast-model"


def test_routing_disabled_without_model_long():
    agent = DummyAgent(model="quality-model", route_threshold_chars=10)
    assert agent.pick_model("x" * 100000) == "quality-model"


def test_run_uses_routed_model():
    captured = {}

    class CapturingAgent(DummyAgent):
        def complete(self, system: str, user: str, model: str | None = None) -> str:
            captured["model"] = model
            return "ok"

    agent = CapturingAgent(model="quality-model", model_long="fast-model", route_threshold_chars=10)
    task = TaskCreate(url="https://example.com", page_text="x" * 50)
    assert agent.run(task) == "ok"
    assert captured["model"] == "fast-model"
