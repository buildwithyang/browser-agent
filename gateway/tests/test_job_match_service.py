from types import SimpleNamespace

from app.agents.job_match import JobMatchAgent
from app.modules.task.schema import TaskCreate
from app.modules.task.service import TaskService


def fake_client(content: str):
    def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def make_service(content: str) -> tuple[TaskService, JobMatchAgent]:
    agent = JobMatchAgent(client=fake_client(content), model="m")
    agent._cv_text = "Go / Kubernetes / 5y backend"
    svc = TaskService(
        agents={"job_match": agent},
        repository=None,
        resume_service=None,
        default_model="m",
    )
    return svc, agent


# 门控要求选中的 JD >= 1000 字;用一段足够长的职位描述。
LONG_JD = (
    "Senior Backend Engineer — we are hiring. Responsibilities: design and operate "
    "high-throughput distributed systems; build gRPC and REST APIs; own reliability, "
    "on-call, and performance tuning for a global consumer-facing platform serving "
    "millions of daily active users. Requirements: 5+ years backend engineering; "
    "expert in Go; solid Kubernetes, message queues, databases, caching, and "
    "observability; proven track record scaling production services under load. "
) * 3


def job_task() -> TaskCreate:
    return TaskCreate(
        url="https://x.com/j",
        title="Senior Go Engineer",
        selected_text=LONG_JD,
        agent="job_match",
    )


def test_stage_one_response_carries_cover_letter_action():
    svc, _ = make_service(
        "@@SECTION conclusion\n匹配度 70。\n@@SECTION overview\n做支付。\n@@SECTION skills\n- Go ✅\n"
    )
    resp = svc.run(job_task(), user_id=None)
    assert [a.id for a in resp.actions] == ["generate_cover_letter"]


def test_continuation_response_has_no_actions():
    svc, _ = make_service("@@SECTION cover_letter\nDear Hiring Manager\n")
    task = TaskCreate(
        url="https://x.com/j",
        title="Senior Go Engineer",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n匹配度 70。\n",
        agent="job_match",
    )
    resp = svc.run(task, user_id=None)
    assert resp.actions == []
    # 返回的是合并后的全量区块
    assert [s.id for s in resp.sections][0] == "conclusion"
    assert any(s.id == "cover_letter" for s in resp.sections)
