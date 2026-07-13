# Quick Insight Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the extension's two agent-specific context-menu entries with one Browser Agent entry that routes LinkedIn/Indeed job pages to a structured job-match Quick Insight and all other pages to a generic summary, while removing Gateway URL from the user-facing popup.

**Architecture:** The extension always sends `agent="browser_agent"`. A task-module router converts that request to `job_match` when the selected JD is long enough and the host is LinkedIn or Indeed; otherwise it safely selects `summary_page`. Agents produce a typed `QuickInsight` on `TaskResponse`, and the extension renders that structure without extracting scores from HTML. This milestone keeps the existing overlay and hides actions whose `enabled` flag is false; opening Side Panel Current Tasks is Milestone 2.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, Chrome Extension Manifest V3, plain ES modules, Node test runner.

## Global Constraints

- Read the relevant module `README.md` before modifying that module.
- Gateway code must preserve `API -> Service -> Repository -> DB`; routing belongs in task service/module code, not `api.py`.
- `core/` must not depend on `modules/`.
- Agents remain stateless; user CV text is injected per request.
- SQLite and PostgreSQL behavior must remain compatible; this milestone changes no tables.
- LinkedIn/Indeed routing requires a matching host and at least `MIN_JOB_CONTENT_CHARS == 1000` selected characters.
- Any uncertain route falls back to `summary_page`; it must not fail because page type is unknown.
- Match score is a typed integer from 0 through 100, never parsed from rendered HTML.
- Quick Insight renders at most one top strength and one top gap.
- Unimplemented actions are omitted from the UI; do not show dead or “coming soon” controls.
- `job_match` Quick Insight responses return no actions in Milestone 1; explicit legacy
  stage-one `job_match` requests still expose `generate_cover_letter`, while continuation
  responses remain action-free.
- Milestone 2 will add a `Summary` Action for LinkedIn/Indeed job contexts alongside
  `Deep Analysis` and `Write Cover Letter`.
- Production gateway is `https://browser.buildwithyang.com/api`; local development gateway is `http://127.0.0.1:17321`.
- Do not log page body, CV text, prompts, tokens, or full external responses.
- Run gateway tests from `gateway/` with `uv run pytest`; run extension tests from `extension/` with `npm test`.
- Update `extension/README.md` and this design's documents when behavior changes.

---

## File Structure

- `gateway/app/modules/task/router.py` — pure page-context routing; no HTTP and no agent execution.
- `gateway/app/modules/task/schema.py` — Browser Agent input name plus typed Quick Insight and Action contracts.
- `gateway/app/modules/task/service.py` — resolves `browser_agent`, executes the selected agent, builds `TaskResponse.insight`.
- `gateway/app/agents/job_match.py` — emits and parses structured Quick Insight fields for job pages.
- `gateway/app/agents/summary_page.py` — wraps its existing summary as generic Quick Insight.
- `gateway/tests/test_task_router.py` — router boundary tests.
- `gateway/tests/test_task_schema.py` — schema validation tests.
- `gateway/tests/test_job_match.py` — structured job insight parsing tests.
- `gateway/tests/test_summary_page.py` — generic insight tests.
- `gateway/tests/test_task_service.py` — service routing and response integration tests.
- `extension/config.js` — single production/local gateway selection function.
- `extension/config.test.js` — environment-selection unit tests.
- `extension/quick-insight.js` — pure normalization/view-model helpers for the overlay.
- `extension/quick-insight.test.js` — decision-card and summary view-model tests.
- `extension/background.js` — one menu entry, Browser Agent request, typed Quick Insight rendering.
- `extension/popup.html` / `extension/popup.js` — output language only.
- `extension/package.sh` — packages the production gateway configuration explicitly.
- `extension/README.md` — user and developer instructions.

---

### Task 1: Typed Browser Agent and Quick Insight Contracts

**Files:**
- Modify: `gateway/app/modules/task/schema.py`
- Modify: `gateway/tests/test_task_schema.py`

**Interfaces:**
- Consumes: existing `TaskCreate`, `TaskResponse`, and `Action` models.
- Produces:
  - `AgentName` including `"browser_agent"`.
  - `Recommendation = Literal["strong_apply", "apply", "cautious", "skip"]`.
  - `JobOverview(industry_business: str, role_focus: str, summary: str)`.
  - `QuickInsight(type, title, summary_html, score, recommendation, reason, job_overview, top_strength, top_gap)`.
  - `Action.task_type: str`, `Action.enabled: bool` while preserving `sections` for the existing continuation path.
  - `TaskResponse.insight: QuickInsight | None`.

- [ ] **Step 1: Add failing schema tests**

Append to `gateway/tests/test_task_schema.py`:

```python
import pytest
from pydantic import ValidationError

from app.modules.task.schema import JobOverview, QuickInsight


def test_browser_agent_is_valid_input_name():
    assert TaskCreate(url="https://example.com", agent="browser_agent").agent == "browser_agent"


def test_job_quick_insight_shape():
    insight = QuickInsight(
        type="job_match",
        title="Job Match",
        score=87,
        recommendation="apply",
        reason="Core requirements match; direct payments experience is missing.",
        job_overview=JobOverview(
            industry_business="Fintech · B2B payments",
            role_focus="Transaction-platform backend",
            summary="Build reliable payment services.",
        ),
        top_strength="Go and distributed systems",
        top_gap="Direct payments experience",
    )
    assert insight.score == 87
    assert insight.job_overview.role_focus == "Transaction-platform backend"


def test_quick_insight_rejects_score_outside_range():
    with pytest.raises(ValidationError):
        QuickInsight(type="job_match", title="Job Match", score=101)


def test_summary_quick_insight_has_no_job_score():
    insight = QuickInsight(
        type="summary",
        title="Page Summary",
        summary_html="<p>Key point.</p>",
    )
    assert insight.score is None
    assert insight.job_overview is None


def test_action_supports_current_task_metadata():
    action = Action(
        id="ask_more",
        label="Ask more",
        task_type="ask_more",
        enabled=False,
        sections=[],
    )
    assert action.task_type == "ask_more"
    assert action.enabled is False
```

- [ ] **Step 2: Run the schema tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_task_schema.py -v`

Expected: FAIL because `JobOverview`, `QuickInsight`, `browser_agent`, and the new Action fields do not exist.

- [ ] **Step 3: Add the schema models and fields**

In `gateway/app/modules/task/schema.py`, replace `AgentName` and extend the response contracts with:

```python
class AgentName(StrEnum):
    BROWSER_AGENT = "browser_agent"
    SUMMARY_PAGE = "summary_page"
    JOB_MATCH = "job_match"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OPENCLAW = "openclaw"


Recommendation = Literal["strong_apply", "apply", "cautious", "skip"]


class JobOverview(BaseModel):
    industry_business: str
    role_focus: str
    summary: str


class QuickInsight(BaseModel):
    type: Literal["job_match", "summary"]
    title: str
    summary_html: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None
    reason: str = ""
    job_overview: JobOverview | None = None
    top_strength: str = ""
    top_gap: str = ""


class Action(BaseModel):
    id: str
    label: str
    sections: list[str] = Field(default_factory=list)
    task_type: str = ""
    enabled: bool = True
```

Add to `TaskResponse` immediately after `actions`:

```python
    insight: QuickInsight | None = None
```

- [ ] **Step 4: Run the schema tests**

Run: `cd gateway && uv run pytest tests/test_task_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the contract**

```bash
git add gateway/app/modules/task/schema.py gateway/tests/test_task_schema.py
git commit -m "feat(task): add typed quick insight contract"
```

---

### Task 2: Pure Page-Context Router

**Files:**
- Create: `gateway/app/modules/task/router.py`
- Create: `gateway/tests/test_task_router.py`

**Interfaces:**
- Consumes: `TaskCreate` and `MIN_JOB_CONTENT_CHARS`.
- Produces: `route_browser_task(task: TaskCreate) -> Literal["job_match", "summary_page"]`.

- [ ] **Step 1: Write failing router tests**

Create `gateway/tests/test_task_router.py`:

```python
from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.router import route_browser_task
from app.modules.task.schema import TaskCreate


LONG_JD = "Responsibilities and requirements for this engineering role. " * 30
assert len(LONG_JD) >= MIN_JOB_CONTENT_CHARS


def task(url: str, selected: str = LONG_JD) -> TaskCreate:
    return TaskCreate(url=url, selectedText=selected, agent="browser_agent")


def test_linkedin_job_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://www.linkedin.com/jobs/view/123")) == "job_match"


def test_indeed_job_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://ae.indeed.com/viewjob?jk=abc")) == "job_match"


def test_linkedin_profile_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://www.linkedin.com/in/someone")) == "job_match"


def test_linkedin_search_results_with_current_job_routes_to_job_match():
    assert route_browser_task(
        task("https://www.linkedin.com/jobs/search-results/?currentJobId=4439779617")
    ) == "job_match"


def test_linkedin_collections_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://www.linkedin.com/jobs/collections")) == "job_match"


def test_indeed_page_with_full_selection_routes_to_job_match():
    assert route_browser_task(task("https://ae.indeed.com/jobs?notjk=value")) == "job_match"


def test_job_url_with_short_selection_falls_back_to_summary():
    assert route_browser_task(task("https://www.linkedin.com/jobs/view/123", "short")) == "summary_page"


def test_indeed_page_with_short_selection_falls_back_to_summary():
    assert route_browser_task(task("https://ae.indeed.com/jobs", "short")) == "summary_page"


def test_unknown_site_falls_back_to_summary():
    assert route_browser_task(task("https://example.com/jobs/123")) == "summary_page"
```

- [ ] **Step 2: Run the router tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_task_router.py -v`

Expected: FAIL with `ModuleNotFoundError: app.modules.task.router`.

- [ ] **Step 3: Implement deterministic routing**

Create `gateway/app/modules/task/router.py`:

```python
from __future__ import annotations

from urllib.parse import urlparse

from app.agents.job_match import MIN_JOB_CONTENT_CHARS
from app.modules.task.schema import AgentName, TaskCreate


def _is_linkedin_host(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _is_indeed_host(host: str) -> bool:
    return host == "indeed.com" or host.endswith(".indeed.com")


def route_browser_task(task: TaskCreate) -> AgentName:
    parsed = urlparse(task.url)
    host = (parsed.hostname or "").lower()
    has_full_jd = len(task.selected_text.strip()) >= MIN_JOB_CONTENT_CHARS
    is_supported_host = _is_linkedin_host(host) or _is_indeed_host(host)
    return (
        AgentName.JOB_MATCH
        if is_supported_host and has_full_jd
        else AgentName.SUMMARY_PAGE
    )
```

- [ ] **Step 4: Run router tests**

Run: `cd gateway && uv run pytest tests/test_task_router.py -v`

Expected: PASS (9 tests).

- [ ] **Step 5: Commit the router**

```bash
git add gateway/app/modules/task/router.py gateway/tests/test_task_router.py
git commit -m "feat(task): route browser context by page type"
```

---

### Task 3: Structured Job Quick Insight

**Files:**
- Modify: `gateway/app/agents/job_match.py`
- Modify: `gateway/tests/test_job_match.py`

**Interfaces:**
- Consumes: `QuickInsight`, `JobOverview`, `TaskCreate`, existing model completion.
- Produces: `JobMatchAgent.build_insight(result: str, lang: str) -> QuickInsight`.
- Model marker: `@@INSIGHT` followed by exactly one JSON object.

- [ ] **Step 1: Add failing insight tests**

Append to `gateway/tests/test_job_match.py`:

```python
def test_build_insight_parses_typed_job_decision():
    agent = JobMatchAgent()
    raw = '''@@INSIGHT
{"score":87,"recommendation":"apply","reason":"核心要求基本命中。","industry_business":"金融科技 · B2B 支付","role_focus":"交易平台后端","summary":"负责高可用支付服务。","top_strength":"Go 与分布式系统","top_gap":"缺少直接支付经验"}'''
    insight = agent.build_insight(raw, "zh")
    assert insight.type == "job_match"
    assert insight.score == 87
    assert insight.recommendation == "apply"
    assert insight.job_overview.industry_business == "金融科技 · B2B 支付"
    assert insight.top_strength == "Go 与分布式系统"


def test_build_insight_rejects_invalid_json():
    agent = JobMatchAgent()
    with pytest.raises(ValueError, match="Quick Insight"):
        agent.build_insight("@@INSIGHT\nnot json", "zh")


def test_quick_insight_prompt_requests_only_decision_fields():
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5 years"
    task = make_task().model_copy(update={"agent": "job_match", "intent": "quick_insight"})
    prompt = agent.build_prompt(task)
    assert "@@INSIGHT" in prompt
    assert '"score"' in prompt
    assert "cover_letter" not in prompt
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_job_match.py -k "insight" -v`

Expected: FAIL because `build_insight` and the Quick Insight prompt branch do not exist.

- [ ] **Step 3: Implement the prompt branch and strict parser**

In `gateway/app/agents/job_match.py`, import `json`, `JobOverview`, and `QuickInsight`, then add:

```python
QUICK_INSIGHT_INSTRUCTION = '''
只输出 `@@INSIGHT` 一行和紧随其后的一个 JSON 对象，不输出 Markdown 或额外文字。
JSON 必须包含这些字段：
{"score":0,"recommendation":"apply","reason":"一句核心判断","industry_business":"行业与业务","role_focus":"岗位核心","summary":"1-2句职责摘要","top_strength":"最重要的一项优势","top_gap":"最重要的一项差距"}
recommendation 只能是 strong_apply、apply、cautious、skip。score 必须是 0-100 整数。
评分继续遵守核心要求缺失不高于 65、多项部分满足不高于 75、基本命中 80+ 的克制标尺。
'''.strip()


def _insight_title(lang: str) -> str:
    return "Job Match" if lang == "en" else "岗位匹配"
```

At the start of `build_prompt`, after validation and CV resolution, add this exact branch before the existing section prompt:

```python
        cv = self._resolve_cv_text(cv_text)[:MAX_CV_CHARS]
        if task.intent == "quick_insight":
            return "\n".join(
                [
                    QUICK_INSIGHT_INSTRUCTION,
                    "",
                    "# 我的简历",
                    cv,
                    "",
                    "# 当前招聘职位(用户在页面上选中的内容)",
                    f"标题: {task.title}",
                    f"链接: {task.url}",
                    "职位描述(选中文字):",
                    task.selected_text.strip(),
                    "图片线索(alt/说明):",
                    task.image_text.strip() or "(无)",
                ]
            )
```

Reuse the `cv` local in the existing continuation/default branches; do not resolve the CV a second time.

Add to `JobMatchAgent`:

```python
    def build_insight(self, result: str, lang: str) -> QuickInsight:
        marker, sep, payload = result.partition("@@INSIGHT")
        if marker.strip() or not sep:
            raise ValueError("Quick Insight response is missing @@INSIGHT")
        try:
            data = json.loads(payload.strip())
            return QuickInsight(
                type="job_match",
                title=_insight_title(lang),
                score=data["score"],
                recommendation=data["recommendation"],
                reason=data["reason"],
                job_overview=JobOverview(
                    industry_business=data["industry_business"],
                    role_focus=data["role_focus"],
                    summary=data["summary"],
                ),
                top_strength=data["top_strength"],
                top_gap=data["top_gap"],
            )
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Quick Insight response is invalid") from exc
```

- [ ] **Step 4: Run job-match tests**

Run: `cd gateway && uv run pytest tests/test_job_match.py -v`

Expected: PASS, including existing section and continuation behavior.

- [ ] **Step 5: Commit structured job insight**

```bash
git add gateway/app/agents/job_match.py gateway/tests/test_job_match.py
git commit -m "feat(job-match): return structured quick insight"
```

---

### Task 4: Generic Summary Quick Insight

**Files:**
- Modify: `gateway/app/agents/summary_page.py`
- Modify: `gateway/tests/test_summary_page.py`

**Interfaces:**
- Consumes: existing summary result and `render_markdown`.
- Produces: `SummaryPageAgent.build_insight(result: str, lang: str) -> QuickInsight` and disabled `Ask more` action metadata for Milestone 2.

- [ ] **Step 1: Add failing generic-insight tests**

Append to `gateway/tests/test_summary_page.py`:

```python
def test_summary_builds_generic_quick_insight():
    agent = SummaryPageAgent()
    insight = agent.build_insight("**Release:** Version 2.0 ships Friday.", "en")
    assert insight.type == "summary"
    assert insight.title == "Page Summary"
    assert "<strong>Release:</strong>" in insight.summary_html
    assert insight.score is None


def test_summary_declares_ask_more_for_next_milestone_but_disabled():
    agent = SummaryPageAgent()
    actions = agent.actions(full_page_task(), "en")
    assert len(actions) == 1
    assert actions[0].id == "ask_more"
    assert actions[0].task_type == "ask_more"
    assert actions[0].enabled is False
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_summary_page.py -k "insight or ask_more" -v`

Expected: FAIL because the methods do not exist.

- [ ] **Step 3: Implement generic insight and action metadata**

In `gateway/app/agents/summary_page.py`, import `Action`, `QuickInsight`, and `render_markdown`; add:

```python
    def build_insight(self, result: str, lang: str) -> QuickInsight:
        return QuickInsight(
            type="summary",
            title="Page Summary" if lang == "en" else "页面摘要",
            summary_html=render_markdown(result),
        )

    def actions(self, task: TaskCreate, lang: str) -> list[Action]:
        return [
            Action(
                id="ask_more",
                label="Ask more" if lang == "en" else "继续提问",
                task_type="ask_more",
                enabled=False,
            )
        ]
```

- [ ] **Step 4: Run summary tests**

Run: `cd gateway && uv run pytest tests/test_summary_page.py -v`

Expected: PASS.

- [ ] **Step 5: Commit generic insight**

```bash
git add gateway/app/agents/summary_page.py gateway/tests/test_summary_page.py
git commit -m "feat(summary): expose generic quick insight"
```

---

### Task 5: Route and Assemble Quick Insight in TaskService

**Files:**
- Modify: `gateway/app/modules/task/service.py`
- Create: `gateway/tests/test_task_service.py`

**Interfaces:**
- Consumes: `route_browser_task`, `agent.build_insight(result, lang)`, existing agent map.
- Produces: routed `TaskResponse.request.agent`, `TaskResponse.insight`, and existing result fallbacks.

- [ ] **Step 1: Add failing service integration tests**

Create `gateway/tests/test_task_service.py` if absent, using a small fake agent:

```python
from types import SimpleNamespace

from app.modules.task.schema import AgentName, QuickInsight, TaskCreate
from app.modules.task.service import TaskService


class FakeAgent:
    def __init__(self, name):
        self.name = name

    def build_prompt(self, task, **kwargs):
        return f"prompt:{self.name}"

    def run(self, task, **kwargs):
        return f"result:{self.name}"

    def build_insight(self, result, lang):
        return QuickInsight(type="summary", title=self.name, summary_html=f"<p>{result}</p>")

    def actions(self, task, lang):
        return []


def service():
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
    assert response.insight.title == "summary_page"


def test_explicit_summary_agent_is_not_rerouted():
    response = service().run(
        TaskCreate(url="https://www.linkedin.com/jobs/view/1", agent="summary_page"),
        user_id=None,
    )
    assert response.request.agent == "summary_page"
```

- [ ] **Step 2: Run service tests and verify failure**

Run: `cd gateway && uv run pytest tests/test_task_service.py -v`

Expected: FAIL with `Unsupported agent: browser_agent`.

- [ ] **Step 3: Resolve Browser Agent before agent lookup**

In `TaskService.run`, before `_agents.get`, add:

```python
        if task.agent is AgentName.BROWSER_AGENT:
            routed = route_browser_task(task)
            task = task.model_copy(
                update={
                    "agent": routed,
                    "intent": (
                        "quick_insight"
                        if routed is AgentName.JOB_MATCH
                        else task.intent
                    ),
                }
            )
```

Import `route_browser_task`. After `actions` are built, build insight with:

```python
            insight = (
                agent.build_insight(result, task.lang)
                if hasattr(agent, "build_insight")
                else None
            )
```

Pass `insight=insight` into `TaskResponse`.

Because the test fake named `job_match` is not a `JobMatchAgent`, keep its test on the summary route; real job CV injection remains covered by existing service/job-match tests.

- [ ] **Step 4: Run service and gateway tests**

Run: `cd gateway && uv run pytest tests/test_task_service.py tests/test_task_router.py tests/test_job_match.py tests/test_summary_page.py -v`

Expected: PASS.

- [ ] **Step 5: Commit service integration**

```bash
git add gateway/app/modules/task/service.py gateway/tests/test_task_service.py
git commit -m "feat(task): route and assemble quick insights"
```

---

### Task 6: Production/Local Gateway Configuration Without Popup Storage

**Files:**
- Create: `extension/config.js`
- Create: `extension/config.test.js`
- Modify: `extension/auth.js`
- Modify: `extension/auth.test.js`
- Modify: `extension/background.js`
- Modify: `extension/package.sh`
- Modify: `extension/package.json`

**Interfaces:**
- Produces: `gatewayForEnvironment(env: string | undefined) -> string`.
- Runtime convention: source/load-unpacked defaults to local; `package.sh` stages a generated `config.js` whose default is production.

- [ ] **Step 1: Write failing configuration tests**

Create `extension/config.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";

import { LOCAL_GATEWAY, PRODUCTION_GATEWAY, gatewayForEnvironment } from "./config.js";

test("source build defaults to local gateway", () => {
  assert.equal(gatewayForEnvironment(undefined), LOCAL_GATEWAY);
});

test("production environment selects cloud gateway", () => {
  assert.equal(gatewayForEnvironment("production"), PRODUCTION_GATEWAY);
});
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd extension && node --test config.test.js`

Expected: FAIL because `config.js` does not exist.

- [ ] **Step 3: Add configuration and remove gateway storage reads**

Create `extension/config.js`:

```javascript
export const LOCAL_GATEWAY = "http://127.0.0.1:17321";
export const PRODUCTION_GATEWAY = "https://browser.buildwithyang.com/api";
export const BUILD_ENV = "development";

export function gatewayForEnvironment(env = BUILD_ENV) {
  return env === "production" ? PRODUCTION_GATEWAY : LOCAL_GATEWAY;
}

export const GATEWAY_BASE = gatewayForEnvironment();
```

In `auth.js`, import and re-export `GATEWAY_BASE as DEFAULT_GATEWAY`; remove `GATEWAY_KEY`. In `background.js`, remove `GATEWAY_KEY` and change `getGatewayConfig()` to:

```javascript
function getGatewayConfig() {
  return chrome.storage.local
    .get({ [TOKEN_KEY]: "" })
    .then((cfg) => ({ base: DEFAULT_GATEWAY, token: cfg[TOKEN_KEY] }));
}
```

Remove all tests/imports that assert `GATEWAY_KEY` behavior; keep URL composition tests using `DEFAULT_GATEWAY`.

- [ ] **Step 4: Make packaging stage production config**

Add `config.js` to `FILES` in `extension/package.sh`. For both normal and `--store` modes, always stage files in `mktemp -d`, then replace this exact line in staged `config.js`:

```javascript
export const BUILD_ENV = "development";
```

with:

```javascript
export const BUILD_ENV = "production";
```

Zip only from the staged directory. Add a post-package assertion:

```bash
unzip -p "$ZIP" config.js | grep -q 'BUILD_ENV = "production"' || {
  echo "package.sh: production gateway config missing" >&2
  exit 1
}
```

Add to `extension/package.json` scripts:

```json
"test:package": "npm run package && unzip -p dist/agent-bridge-extension.zip config.js | grep -q 'BUILD_ENV = \\\"production\\\"'"
```

- [ ] **Step 5: Run extension configuration and package tests**

Run: `cd extension && npm test && npm run test:package`

Expected: all Node tests PASS; package assertion exits 0 and the staged archive contains production configuration while source `config.js` remains development.

- [ ] **Step 6: Commit environment configuration**

```bash
git add extension/config.js extension/config.test.js extension/auth.js extension/auth.test.js extension/background.js extension/package.sh extension/package.json
git commit -m "feat(ext): separate local and production gateways"
```

---

### Task 7: One Browser Agent Menu and Typed Quick Insight Renderer

**Files:**
- Create: `extension/quick-insight.js`
- Create: `extension/quick-insight.test.js`
- Modify: `extension/background.js`

**Interfaces:**
- Consumes: `TaskResponse.insight`, `TaskResponse.actions`.
- Produces: `quickInsightView(insight, actions) -> normalized view object` containing only enabled actions.

- [ ] **Step 1: Write failing view-model tests**

Create `extension/quick-insight.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";

import { quickInsightView } from "./quick-insight.js";

test("job insight keeps typed decision fields", () => {
  const view = quickInsightView({
    type: "job_match",
    title: "Job Match",
    score: 87,
    recommendation: "apply",
    reason: "Core requirements match.",
    job_overview: {
      industry_business: "Fintech · B2B payments",
      role_focus: "Transaction backend",
      summary: "Build reliable payment services.",
    },
    top_strength: "Go",
    top_gap: "Payments experience",
  }, []);
  assert.equal(view.score, 87);
  assert.equal(view.overview.roleFocus, "Transaction backend");
});

test("disabled actions are omitted", () => {
  const view = quickInsightView(
    { type: "summary", title: "Page Summary", summary_html: "<p>Summary</p>" },
    [{ id: "ask_more", label: "Ask more", enabled: false }]
  );
  assert.deepEqual(view.actions, []);
});
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd extension && node --test quick-insight.test.js`

Expected: FAIL because `quick-insight.js` does not exist.

- [ ] **Step 3: Add pure view normalization**

Create `extension/quick-insight.js`:

```javascript
export function quickInsightView(insight = {}, actions = []) {
  const overview = insight.job_overview || {};
  return {
    type: insight.type || "summary",
    title: insight.title || "Quick Insight",
    summaryHtml: insight.summary_html || "",
    score: Number.isInteger(insight.score) ? insight.score : null,
    recommendation: insight.recommendation || "",
    reason: insight.reason || "",
    overview: {
      industryBusiness: overview.industry_business || "",
      roleFocus: overview.role_focus || "",
      summary: overview.summary || "",
    },
    topStrength: insight.top_strength || "",
    topGap: insight.top_gap || "",
    actions: actions.filter((action) => action.enabled !== false),
  };
}
```

- [ ] **Step 4: Replace two context menus with one**

In `extension/background.js`:

- Replace `MENU_AGENT` with `const MENU_ID = "browser-agent"`.
- Replace localized titles with `"Browser Agent"` in both languages.
- Create exactly one context menu for `page` and `selection`.
- Remove `pendingAgent`; context messages always send `agent: "browser_agent"`.
- Keep `pendingSelection` unchanged.
- Pass `insight: task.insight || null` into `showResult`.

The request body must be:

```javascript
buildTaskBody(payload, { agent: "browser_agent", lang })
```

- [ ] **Step 5: Render the decision card and generic summary**

Import `quickInsightView`. Inside `renderPanel`, before legacy `sections` rendering:

```javascript
  } else if (payload.insight) {
    const view = payload.insightView;
    // job_match: score + recommendation + reason + overview + top strength/gap
    // summary: sanitized summaryHtml only
```

Because an injected function cannot close over module imports, compute the plain view object in the service worker payload:

```javascript
insightView: task.insight ? quickInsightView(task.insight, task.actions || []) : null,
```

Inside `renderPanel`, add this helper immediately after `copyTextTo`:

```javascript
  const appendText = (parent, tag, cls, text) => {
    const node = el(tag, cls);
    node.textContent = text;
    parent.append(node);
    return node;
  };

  const renderQuickInsight = (container, view, lang) => {
    const labels = lang === "en"
      ? {
          strong_apply: "Strong match",
          apply: "Worth applying",
          cautious: "Apply cautiously",
          skip: "Low priority",
          industry: "Industry & Business",
          role: "Role Focus",
          strength: "Top Strength",
          gap: "Top Gap",
        }
      : {
          strong_apply: "强烈建议申请",
          apply: "值得申请",
          cautious: "谨慎申请",
          skip: "优先级较低",
          industry: "行业与业务",
          role: "岗位核心",
          strength: "最大优势",
          gap: "最大差距",
        };

    appendText(container, "div", "qi-title", view.title);
    if (view.type === "summary") {
      const summary = el("div", "qi-summary");
      summary.innerHTML = view.summaryHtml;
      container.append(summary);
      return;
    }

    const decision = el("section", "qi-decision");
    const score = el("div", "qi-score");
    appendText(score, "strong", "qi-score-number", String(view.score));
    appendText(score, "span", "qi-score-total", "/100");
    decision.append(score);
    const verdict = el("div", "qi-verdict");
    appendText(
      verdict,
      "span",
      `qi-recommendation qi-${view.recommendation}`,
      labels[view.recommendation] || view.recommendation
    );
    appendText(verdict, "p", "qi-reason", view.reason);
    decision.append(verdict);
    container.append(decision);

    const overview = el("section", "qi-overview");
    const facts = el("div", "qi-facts");
    const industry = el("div", "qi-fact");
    appendText(industry, "span", "qi-label", labels.industry);
    appendText(industry, "strong", "qi-value", view.overview.industryBusiness);
    const role = el("div", "qi-fact");
    appendText(role, "span", "qi-label", labels.role);
    appendText(role, "strong", "qi-value", view.overview.roleFocus);
    facts.append(industry, role);
    overview.append(facts);
    appendText(overview, "p", "qi-overview-summary", view.overview.summary);
    container.append(overview);

    const signals = el("section", "qi-signals");
    if (view.topStrength) {
      const strength = el("div", "qi-signal");
      appendText(strength, "span", "qi-label", labels.strength);
      appendText(strength, "p", "qi-signal-text", view.topStrength);
      signals.append(strength);
    }
    if (view.topGap) {
      const gap = el("div", "qi-gap");
      appendText(gap, "span", "qi-label", labels.gap);
      appendText(gap, "p", "qi-gap-text", view.topGap);
      signals.append(gap);
    }
    container.append(signals);
  };
```

Add this result branch before legacy `sections` handling:

```javascript
  } else if (payload.insightView) {
    renderQuickInsight(body, payload.insightView, payload.lang);
```

Add the matching CSS within the existing Shadow DOM stylesheet:

```css
    .qi-title { color: var(--text-dim); font: 600 11px var(--mono); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 12px; }
    .qi-decision { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: center; padding: 4px 0 16px; }
    .qi-score { display: flex; align-items: baseline; color: var(--signal); font-family: var(--mono); }
    .qi-score-number { font-size: 48px; line-height: .9; letter-spacing: -.07em; }
    .qi-score-total { color: var(--text-dim); font-size: 11px; margin-left: 4px; }
    .qi-recommendation { display: inline-flex; border-radius: 5px; padding: 3px 8px; background: rgba(111,207,151,.13); color: #6fcf97; font: 600 10px var(--mono); }
    .qi-cautious { color: var(--signal); background: var(--signal-soft); }
    .qi-skip { color: var(--alert); background: rgba(232,132,107,.13); }
    .qi-reason { margin: 8px 0 0; font-weight: 600; line-height: 1.45; }
    .qi-overview, .qi-signals > div { border: 1px solid var(--hairline); border-radius: 9px; background: var(--ink-raised); padding: 12px; margin-bottom: 10px; }
    .qi-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
    .qi-fact { background: var(--ink-sunken); border-radius: 7px; padding: 9px; }
    .qi-label { display: block; color: var(--text-dim); font: 600 9px var(--mono); letter-spacing: .08em; text-transform: uppercase; margin-bottom: 3px; }
    .qi-value { display: block; font-size: 12px; }
    .qi-overview-summary, .qi-signal-text, .qi-gap-text { margin: 0; font-size: 12.5px; }
    .qi-summary > :first-child { margin-top: 0; }
    .qi-summary > :last-child { margin-bottom: 0; }
```

Do not parse `payload.html` or `payload.text` for a number.

- [ ] **Step 6: Run extension tests**

Run: `cd extension && npm test`

Expected: PASS, including auth, connection, configuration, and Quick Insight tests.

- [ ] **Step 7: Commit unified entry and renderer**

```bash
git add extension/quick-insight.js extension/quick-insight.test.js extension/background.js
git commit -m "feat(ext): add unified quick insight flow"
```

---

### Task 8: Remove Gateway UI and Update User Documentation

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`
- Modify: `extension/README.md`
- Modify: `docs/superpowers/specs/2026-07-12-browser-agent-interaction-design.md` only if implementation reveals a contract correction.

**Interfaces:**
- Popup continues to store only `langPref` in `chrome.storage.sync`.
- No user-facing component reads or writes `gatewayUrl`.

- [ ] **Step 1: Add a static popup regression test**

Create `extension/popup.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("popup exposes language only", async () => {
  const [html, js] = await Promise.all([
    readFile(new URL("./popup.html", import.meta.url), "utf8"),
    readFile(new URL("./popup.js", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(html, /Gateway URL|网关地址|id="gateway"/);
  assert.doesNotMatch(js, /gatewayInput|GATEWAY_KEY|gatewayUrl/);
  assert.match(html, /Output language/);
  assert.match(js, /langPref/);
});
```

- [ ] **Step 2: Run the popup test and verify failure**

Run: `cd extension && node --test popup.test.js`

Expected: FAIL because the Gateway URL field and JavaScript still exist.

- [ ] **Step 3: Remove gateway controls**

From `popup.html`, delete the Gateway label, input, and hint. From `popup.js`, delete the `auth.js` import and all gateway storage code. Keep the language initialization/change handlers unchanged.

- [ ] **Step 4: Rewrite affected README sections**

Update `extension/README.md` so it states:

- Popup controls output language only.
- There is one `Browser Agent` context-menu entry.
- Backend routing selects LinkedIn/Indeed job matching or generic summary.
- Load-unpacked source uses `http://127.0.0.1:17321`.
- Packaged/store builds use `https://browser.buildwithyang.com/api`.
- Custom self-hosted Gateway URL is not a normal-user setting.
- Quick Insight is the overlay; Side Panel Current Task is the next milestone.

- [ ] **Step 5: Run all verification**

Run:

```bash
cd gateway && uv run pytest
cd ../extension && npm test
npm run test:package
```

Expected: all gateway tests PASS; all extension tests PASS; the packaged archive contains production config.

- [ ] **Step 6: Perform manual acceptance**

Load `extension/` unpacked and verify:

1. Popup contains only the four language options.
2. Context menu contains exactly one `Browser Agent` entry.
3. A selected LinkedIn/Indeed JD of at least 1000 characters shows a typed score card with job overview, one strength, and one gap.
4. A normal webpage shows generic Page Summary.
5. A LinkedIn/Indeed selection shorter than 1000 characters falls back to Page Summary; any path on either host with a full selection enters Job Match.
6. No dead Ask more, Tailor Resume, or Mock Interview button appears.

- [ ] **Step 7: Commit docs and popup cleanup**

```bash
git add extension/popup.html extension/popup.js extension/popup.test.js extension/README.md
git commit -m "docs(ext): document quick insight workflow"
```

---

## Plan Self-Review Result

- Spec coverage: Milestone 1 covers Popup simplification, one Browser Agent entry, safe Context Routing, typed job Quick Insight, generic Summary fallback, and hidden unavailable actions.
- Deferred by design: Side Panel Current Task and Follow-up are Milestones 2 and 3 and require separate implementation plans.
- Type consistency: request uses `agent="browser_agent"`; routing resolves to existing `job_match` or `summary_page`; response uses `insight`; action navigation metadata uses `task_type`.
- Privacy: no new raw page, CV, prompt, or response logging is introduced.
- Database: no schema or deployment SQL change is required.
