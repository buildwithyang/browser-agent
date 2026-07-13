# Agent Name Enum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace gateway-internal bare Agent name strings with one central `AgentName(StrEnum)` without changing the extension API or database representation.

**Architecture:** `gateway/app/modules/task/schema.py` owns the enum because it already owns the task input and output contracts. Router, Service, agent adapters, agent registry, and task record domain objects consume the same enum. Pydantic and SQLAlchemy boundaries continue serializing and storing each member's existing string value.

**Tech Stack:** Python 3.13, `enum.StrEnum`, Pydantic v2, FastAPI, SQLAlchemy, pytest.

## Global Constraints

- Preserve the existing external values: `browser_agent`, `summary_page`, `job_match`, `claude-code`, `codex`, and `openclaw`.
- Do not change the Chrome extension payload or response schema.
- Do not change database columns or PostgreSQL initialization SQL.
- Preserve the user's uncommitted `TaskService.rate_limit_max = 20` change.
- Follow TDD: enum contract tests must fail before production code changes.

---

### Task 1: Centralize Agent Names

**Files:**
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/app/modules/task/router.py`
- Modify: `gateway/app/modules/task/service.py`
- Modify: `gateway/app/modules/task/repo.py`
- Modify: `gateway/app/agents/base.py`
- Modify: `gateway/app/agents/job_match.py`
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/app/main.py`
- Modify: `gateway/tests/test_task_schema.py`
- Modify: `gateway/tests/test_task_router.py`
- Modify: `gateway/tests/test_task_service.py`
- Modify: `gateway/tests/test_task_repo.py`

**Interfaces:**
- Produces: `AgentName(StrEnum)` with `BROWSER_AGENT`, `SUMMARY_PAGE`, `JOB_MATCH`, `CLAUDE_CODE`, `CODEX`, and `OPENCLAW` members.
- Produces: `route_browser_task(task: TaskCreate) -> AgentName`, restricted to `JOB_MATCH` or `SUMMARY_PAGE`.
- Preserves: JSON values remain the existing lowercase strings.

- [ ] **Step 1: Add failing enum contract tests**

```python
def test_taskcreate_parses_agent_name_enum_and_serializes_existing_value():
    task = TaskCreate(url="https://example.com", agent="browser_agent")
    assert task.agent is AgentName.BROWSER_AGENT
    assert task.model_dump(mode="json")["agent"] == "browser_agent"


def test_router_returns_agent_name_enum():
    assert route_browser_task(task("https://www.linkedin.com/jobs")) is AgentName.JOB_MATCH
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd gateway && uv run pytest tests/test_task_schema.py tests/test_task_router.py tests/test_task_service.py tests/test_task_repo.py -q`

Expected: FAIL because the existing `typing.Literal` has no enum members.

- [ ] **Step 3: Implement the enum and replace internal string comparisons**

```python
class AgentName(StrEnum):
    BROWSER_AGENT = "browser_agent"
    SUMMARY_PAGE = "summary_page"
    JOB_MATCH = "job_match"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OPENCLAW = "openclaw"
```

Use enum members in Router, Service, agent `name` fields, the main agent registry, and `TaskRecordData.agent`. Use identity comparisons such as `task.agent is AgentName.BROWSER_AGENT` and `routed is AgentName.JOB_MATCH`.
At the database boundary, `TaskRepository.append()` writes `record.agent.value`; `_to_data()` lets Pydantic parse the stored string back into `AgentName`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd gateway && uv run pytest tests/test_task_schema.py tests/test_task_router.py tests/test_task_service.py tests/test_task_repo.py -q`

Expected: all focused tests PASS.

- [ ] **Step 5: Run full verification**

Run: `cd gateway && uv run pytest`

Expected: all gateway tests PASS and API serialization retains the existing string values.

- [ ] **Step 6: Review the worktree**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; the user's pre-existing `service.py` rate-limit change remains present.
