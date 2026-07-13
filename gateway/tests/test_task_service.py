from app.modules.task.schema import AgentName, QuickInsight, TaskCreate
from app.modules.task.service import TaskService


class FakeAgent:
    def __init__(self, name: AgentName) -> None:
        self.name = name

    def build_prompt(self, task: TaskCreate, **kwargs: object) -> str:
        return f"prompt:{self.name}"

    def run(self, task: TaskCreate, **kwargs: object) -> str:
        return f"result:{self.name}"

    def build_insight(self, result: str, lang: str) -> QuickInsight:
        return QuickInsight(
            type="summary",
            title=self.name.value,
            summary_html=f"<p>{result}</p>",
        )

    def actions(self, task: TaskCreate, lang: str) -> list[object]:
        return []


def service() -> TaskService:
    return TaskService(
        agents={
            AgentName.SUMMARY_PAGE: FakeAgent(AgentName.SUMMARY_PAGE),
            AgentName.JOB_MATCH: FakeAgent(AgentName.JOB_MATCH),
        },
        repository=None,
        resume_service=None,
        default_model="fake",
    )


def test_browser_agent_unknown_page_routes_to_summary():
    response = service().run(
        TaskCreate(
            url="https://example.com/article",
            pageText="Article",
            agent=AgentName.BROWSER_AGENT,
        ),
        user_id=None,
    )

    assert response.request.agent is AgentName.SUMMARY_PAGE
    assert response.insight is not None
    assert response.insight.title == "summary_page"


def test_explicit_summary_agent_is_not_rerouted():
    response = service().run(
        TaskCreate(
            url="https://www.linkedin.com/jobs/view/1",
            agent=AgentName.SUMMARY_PAGE,
        ),
        user_id=None,
    )

    assert response.request.agent is AgentName.SUMMARY_PAGE
