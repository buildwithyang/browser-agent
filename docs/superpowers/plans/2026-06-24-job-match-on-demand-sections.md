# Job Match On-Demand Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `job_match` into a default "match analysis" stage and an on-demand "cover letter + resume tips" stage triggered by a panel button, with a generic JD-agnostic scoring rubric and generation-order decoupled from display-order.

**Architecture:** The right-click task generates only `conclusion + overview + skills`. The gateway returns a new `actions` list declaring follow-up buttons. The extension (a dumb shell) renders those buttons; clicking one re-POSTs to `/tasks` echoing the stage-1 `result` back as `prior_result`, and the gateway generates `cover_letter + resume_tips` from that analysis + the user's CV, returning the merged full result. No DB, no persistence change, no server-side caching.

**Tech Stack:** Python 3.13 / FastAPI / pydantic v2 / pytest (gateway); MV3 Chrome extension, plain ES modules, `node --test` (extension).

## Global Constraints

- Section ids are exactly: `conclusion`, `overview`, `skills`, `cover_letter`, `resume_tips`.
- `DEFAULT_SECTIONS = ["conclusion", "overview", "skills"]` (right-click default).
- `GENERATION_ORDER = ["overview", "skills", "conclusion", "cover_letter", "resume_tips"]` — `skills` MUST precede `conclusion`.
- `DISPLAY_ORDER = ["conclusion", "overview", "skills", "cover_letter", "resume_tips"]` — `conclusion` first.
- The `@@SECTION <id>` marker format and `_SECTION_RE = r"^@@SECTION\s+(\w+)\s*$"` are unchanged; the model must never put extra text on a `@@SECTION` line.
- Extension request fields are camelCase via pydantic aliases (`selectedText`, `pageText`, `priorResult`); response fields stay snake_case (`result_html`, `actions`).
- The conclusion scoring rubric must contain NO hardcoded industry/skill names.
- Run gateway tests from `gateway/` with `uv run pytest`; extension tests from `extension/` with `npm test`.

---

## File Structure

- `gateway/app/modules/task/schema.py` — add `TaskCreate.sections`, `TaskCreate.prior_result`; new `Action` model; `TaskResponse.actions`.
- `gateway/app/agents/job_match.py` — section catalog + 3 order constants; generic rubric; `sections`/continuation aware `validate`/`build_prompt`/`run`; `build_sections` re-sort; new `actions()`.
- `gateway/app/modules/task/service.py` — wire `agent.actions()` into the response (one block).
- `gateway/tests/test_task_schema.py` — NEW, schema unit tests.
- `gateway/tests/test_job_match.py` — extend with sections/ordering/continuation/actions tests; update two existing tests.
- `extension/auth.js` — add pure `buildTaskBody()` helper.
- `extension/auth.test.js` — tests for `buildTaskBody()`.
- `extension/background.js` — dumb-shell: shared `dispatchTask()`, `AGENT_BRIDGE_CONTINUE` handler, action buttons in `renderPanel`.

---

## Task 1: Schema — `sections`, `prior_result`, `Action`, `actions`

**Files:**
- Modify: `gateway/app/modules/task/schema.py`
- Test: `gateway/tests/test_task_schema.py` (create)

**Interfaces:**
- Produces:
  - `TaskCreate.sections: list[str] | None = None`
  - `TaskCreate.prior_result: str | None` (alias `priorResult`, `max_length=50_000`, default `None`)
  - `class Action(BaseModel): id: str; label: str; sections: list[str]`
  - `TaskResponse.actions: list[Action]` (default empty list)

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_task_schema.py`:

```python
from app.modules.task.schema import Action, TaskCreate, TaskResponse


def test_taskcreate_defaults_have_no_sections_or_prior_result():
    t = TaskCreate(url="https://x.com/j")
    assert t.sections is None
    assert t.prior_result is None


def test_taskcreate_accepts_sections_and_prior_result_camel_alias():
    t = TaskCreate(
        url="https://x.com/j",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n匹配度 60。",
    )
    assert t.sections == ["cover_letter", "resume_tips"]
    assert t.prior_result.startswith("@@SECTION conclusion")


def test_taskresponse_actions_default_empty():
    r = TaskResponse(request=TaskCreate(url="https://x.com/j"))
    assert r.actions == []


def test_action_model_shape():
    a = Action(id="generate_cover_letter", label="✍️ 生成求职信",
               sections=["cover_letter", "resume_tips"])
    assert a.id == "generate_cover_letter"
    assert a.sections == ["cover_letter", "resume_tips"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_task_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'Action'` (and attribute errors).

- [ ] **Step 3: Add the schema members**

In `gateway/app/modules/task/schema.py`, add to `TaskCreate` (after the `image_text` field, before `intent`):

```python
    # 按需分阶段:job_match 用。省略=默认分析集;非空=只生成被点名的区块。
    sections: list[str] | None = None
    # 续跑时回传的阶段一 result 文本(求职信/建议基于它生成,无需重传页面正文)。
    prior_result: str | None = Field(default=None, alias="priorResult", max_length=50_000)
```

Add a new `Action` model (place it just above `TaskResponse`):

```python
class Action(BaseModel):
    """结果上可触发的后续动作。后端声明,前端照单渲染按钮(未来新动作纯后端添加)。"""

    id: str
    label: str
    sections: list[str]
```

Add to `TaskResponse` (after the `sections` field):

```python
    actions: list[Action] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_task_schema.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/modules/task/schema.py gateway/tests/test_task_schema.py
git commit -m "feat(schema): add sections/prior_result inputs and actions output"
```

---

## Task 2: job_match catalog, order constants, generic rubric, re-sort

**Files:**
- Modify: `gateway/app/agents/job_match.py:36-78` (replace `SECTION_SPECS`), `:138-164` (`build_prompt`), `:171-201` (`build_sections`)
- Test: `gateway/tests/test_job_match.py`

**Interfaces:**
- Consumes: `SECTION_META` (unchanged), `_SECTION_RE` (unchanged).
- Produces:
  - `SECTION_INSTRUCTIONS: dict[str, str]` (id → instruction)
  - `DEFAULT_SECTIONS`, `GENERATION_ORDER`, `DISPLAY_ORDER` (lists, exact values in Global Constraints)
  - `JobMatchAgent._requested_sections(task) -> list[str]`
  - `build_prompt` emits only requested sections, ordered by `GENERATION_ORDER`
  - `build_sections` returns sections ordered by `DISPLAY_ORDER` (unknown ids stable-sorted last)

- [ ] **Step 1: Write/Update the failing tests**

In `gateway/tests/test_job_match.py`, REPLACE `test_prompt_includes_cv_and_job` (lines 20-34) with:

```python
def test_default_prompt_has_analysis_only():
    agent = JobMatchAgent()
    agent._cv_text = "我会 Go 和 Kubernetes,有 5 年后端经验。"

    prompt = agent.build_prompt(make_task())

    assert "Go 和 Kubernetes" in prompt
    assert "Senior Go Engineer" in prompt
    # 默认右键只跑匹配分析三块
    assert "@@SECTION conclusion" in prompt
    assert "@@SECTION overview" in prompt
    assert "@@SECTION skills" in prompt
    # 求职信/建议默认不生成
    assert "@@SECTION cover_letter" not in prompt
    assert "@@SECTION resume_tips" not in prompt


def test_generation_order_puts_skills_before_conclusion():
    agent = JobMatchAgent()
    agent._cv_text = "Go / 5y backend"
    prompt = agent.build_prompt(make_task())
    assert prompt.index("@@SECTION skills") < prompt.index("@@SECTION conclusion")


def test_build_sections_resorts_to_display_order():
    agent = JobMatchAgent()
    # 模型按生成顺序输出(skills 在 conclusion 前),展示应重排成 conclusion 置顶
    raw = (
        "@@SECTION skills\n- Go ✅\n"
        "@@SECTION conclusion\n匹配度 60。\n"
        "@@SECTION overview\n做支付。\n"
    )
    ids = [s.id for s in agent.build_sections(raw, "zh")]
    assert ids == ["conclusion", "overview", "skills"]


def test_conclusion_rubric_is_generic():
    from app.agents.job_match import SECTION_INSTRUCTIONS
    rubric = SECTION_INSTRUCTIONS["conclusion"]
    assert "AI/LLM" not in rubric          # 不再写死具体技能
    assert "65" in rubric                  # 保留通用评分锚点
    assert "资历过高" in rubric
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && uv run pytest tests/test_job_match.py -k "default_prompt or generation_order or resorts or rubric_is_generic" -v`
Expected: FAIL — `ImportError: cannot import name 'SECTION_INSTRUCTIONS'` / cover_letter still present in default prompt.

- [ ] **Step 3: Replace `SECTION_SPECS` with catalog + order constants (generic rubric)**

In `gateway/app/agents/job_match.py`, replace the whole `SECTION_SPECS = [...]` block (lines 36-78) with:

```python
# 区块生成指令(id -> instruction)。展示标题/复制/折叠见 SECTION_META。
SECTION_INSTRUCTIONS = {
    "conclusion": (
        "用一句话同时给出两点:① 该职位所属的行业 + 具体业务;"
        "② 简历与该职位的匹配评分(0-100)。两者必须都出现在这一句里。"
        "评分务必克制、真实,不给安慰分,并与后面『技能匹配』里的 ✅/⚠️/❌ 自洽。"
        "先识别该岗位『反复强调、决定能否胜任的硬性核心要求』(而非人人都有的通用项),"
        "按核心要求命中情况打分:核心要求出现 ❌ 缺失 → 不应高于 65;"
        "多项核心要求仅 ⚠️ 部分满足 → 不应高于 75;核心要求基本命中、仅边角缺口 → 80+;"
        "几乎全部命中 → 90+。通用基础技能再突出也不能补偿核心要求的缺失;"
        "若经验年限明显超出岗位要求,也要在这句里点明可能被视为『资历过高』。只要这一句,精炼直给。"
    ),
    "overview": (
        "用 2-4 句话客观介绍:这家公司/产品到底在做什么业务、面向什么市场,"
        "以及这个岗位主要负责什么。目的是让用户快速判断自己是否对这个业务方向感兴趣。"
        "只描述,不评价匹配度。"
    ),
    "skills": (
        "站在招聘方筛选的角度,列出该职位要求的关键技能/经验,逐项标注简历是否命中:"
        "✅ 具备 / ⚠️ 部分 / ❌ 缺失,各附一句简要依据。"
        "⚠️/❌ 正是 HR 会质疑的点,可顺带点一句如何弥补或扬长避短。用 Markdown 表格或列表。"
    ),
    "cover_letter": (
        "用 HR/招聘官的阅读习惯,写一封可直接发送、前两句就抓住对方的求职信:"
        "① 开头用一句有冲击力的『钩子』直接点出你最匹配该岗位的核心价值(尽量带量化成果),不要客套寒暄;"
        "② 主体用 2-3 个最相关的匹配点,尽量量化(数字、规模、结果)并呼应 JD 关键词;"
        "③ 结尾给出清晰、自信的下一步意向。全文精炼(约 200-250 字),只要信件正文,不要额外解释或标题。"
    ),
    "resume_tips": (
        "以 HR『6 秒扫一眼』的视角,给出让这份简历瞬间显得『对口』的具体修改建议:"
        "① 哪些与 JD 吻合的关键词/技能要前置、加粗或放到简历靠前位置(兼顾 ATS 关键词筛选);"
        "② 哪些经历应改写成可量化成果——给出『改前 → 改后』的示例措辞;"
        "③ 哪些与该岗位无关的内容可弱化或删减。条理清晰、可直接照做。"
    ),
}

# 右键默认只跑匹配分析三块;求职信/建议按需生成。
DEFAULT_SECTIONS = ["conclusion", "overview", "skills"]
# 喂给模型的顺序:skills 在 conclusion 之前,使评分被技能匹配锚定。
GENERATION_ORDER = ["overview", "skills", "conclusion", "cover_letter", "resume_tips"]
# 回前端的展示顺序:conclusion 置顶(前端把它当 lede)。
DISPLAY_ORDER = ["conclusion", "overview", "skills", "cover_letter", "resume_tips"]
```

- [ ] **Step 4: Add `_requested_sections` and rewrite `build_prompt`'s section lines**

In `JobMatchAgent`, replace `build_prompt` (lines 138-164) with:

```python
    def _requested_sections(self, task: TaskCreate) -> list[str]:
        """请求的区块集合(过滤未知 id);空则回默认分析集。顺序无关,拼 prompt 时按 GENERATION_ORDER 排。"""
        requested = task.sections or DEFAULT_SECTIONS
        valid = [s for s in requested if s in SECTION_INSTRUCTIONS]
        return valid or DEFAULT_SECTIONS

    def _section_request_lines(self, sections: list[str]) -> list[str]:
        lines = ["请按顺序输出以下区块:"]
        for sid in GENERATION_ORDER:
            if sid in sections:
                lines.append(f"@@SECTION {sid} — {SECTION_INSTRUCTIONS[sid]}")
        return lines

    def build_prompt(self, task: TaskCreate, cv_text: str | None = None) -> str:
        # 兜底:任何路径构造 prompt 前都先校验,确保模型不会在稀疏内容上瞎编。
        self.validate(task)
        section_lines = self._section_request_lines(self._requested_sections(task))
        return "\n".join(
            [
                *section_lines,
                "",
                "# 我的简历",
                self._resolve_cv_text(cv_text)[:MAX_CV_CHARS],
                "",
                "# 当前招聘职位页面",
                "标题:",
                task.title,
                "链接:",
                task.url,
                "选中文本:",
                task.selected_text.strip() or "(无)",
                "页面内容:",
                task.page_text.strip() or "(无)",
                "图片线索(alt/说明):",
                task.image_text.strip() or "(无)",
            ]
        )
```

(The continuation branch is added in Task 3; this version still always includes page context.)

- [ ] **Step 5: Re-sort `build_sections` to display order**

In `build_sections`, after the `for` loop builds `sections` and before `return sections` (currently line 201), insert:

```python
        # 生成顺序(skills 先于 conclusion)≠ 展示顺序;按 DISPLAY_ORDER 重排,未知 id 稳定排末尾。
        order = {sid: i for i, sid in enumerate(DISPLAY_ORDER)}
        sections.sort(key=lambda s: order.get(s.id, len(DISPLAY_ORDER)))
```

- [ ] **Step 6: Run the new + full job_match tests**

Run: `cd gateway && uv run pytest tests/test_job_match.py -v`
Expected: PASS — new tests green; `test_build_sections_parses_markers_and_flags` still passes (input already in display order).

- [ ] **Step 7: Commit**

```bash
git add gateway/app/agents/job_match.py gateway/tests/test_job_match.py
git commit -m "feat(job_match): section catalog, generation/display order split, generic rubric"
```

---

## Task 3: job_match `sections` + continuation (`prior_result`)

**Files:**
- Modify: `gateway/app/agents/job_match.py` (`validate`, `build_prompt`, `run`)
- Test: `gateway/tests/test_job_match.py`

**Interfaces:**
- Consumes: `task.prior_result`, `task.sections` (Task 1); `_requested_sections`, `_section_request_lines` (Task 2).
- Produces:
  - `validate` skips the page-content check when `prior_result` is non-empty.
  - `build_prompt` continuation branch: CV + `prior_result`, no page context.
  - `run` continuation: returns `prior_result.rstrip() + "\n\n" + model_output`.

- [ ] **Step 1: Write the failing tests**

Append to `gateway/tests/test_job_match.py`:

```python
def make_continue_task() -> TaskCreate:
    return TaskCreate(
        url="https://example.com/jobs/9",
        title="Senior Go Engineer",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n金融科技,匹配度 82。\n@@SECTION skills\n- Go ✅\n",
    )


def test_continuation_prompt_uses_prior_result_not_page_text():
    agent = JobMatchAgent()
    agent._cv_text = "Go / Kubernetes / 5y backend"
    prompt = agent.build_prompt(make_continue_task())
    assert "@@SECTION cover_letter" in prompt
    assert "@@SECTION resume_tips" in prompt
    assert "@@SECTION conclusion" not in prompt        # 续跑不重生成分析
    assert "金融科技,匹配度 82" in prompt              # 带入阶段一分析
    assert "Go / Kubernetes" in prompt                 # 带入简历


def test_validate_allows_empty_page_when_prior_result_present():
    agent = JobMatchAgent()
    agent._cv_text = "Go"
    # page_text 为空但有 prior_result -> 不抛
    agent.validate(make_continue_task())


def test_run_continuation_prepends_prior_result():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="@@SECTION cover_letter\nDear Hiring Manager\n"))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    agent = JobMatchAgent(client=fake_client, model="gpt-4o-mini")
    agent._cv_text = "Go / 5y"

    result = agent.run(make_continue_task())

    assert result.startswith("@@SECTION conclusion")   # 前序分析在前
    assert "@@SECTION cover_letter" in result          # 模型输出在后
    # 合并文本切块得到全量区块、按展示顺序
    ids = [s.id for s in agent.build_sections(result, "zh")]
    assert ids[0] == "conclusion"
    assert "cover_letter" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && uv run pytest tests/test_job_match.py -k "continuation or validate_allows_empty" -v`
Expected: FAIL — continuation prompt still includes page context / still includes conclusion; validate raises on empty page.

- [ ] **Step 3: Make `validate` continuation-aware**

Replace `validate` (currently lines 126-136) with:

```python
    def validate(self, task: TaskCreate) -> None:
        """内容太少就直接失败,避免模型凭空编造职位/匹配。

        续跑(有 prior_result)时已有阶段一分析,无需页面正文,跳过该检查。
        由 TaskService 在调用模型前预检(抛 ValueError -> API 返回 400,且不耗 token)。
        """
        if task.prior_result and task.prior_result.strip():
            return
        job_chars = max(len(task.page_text.strip()), len(task.selected_text.strip()))
        if job_chars < MIN_JOB_CONTENT_CHARS:
            raise ValueError(
                "这个页面没抓到足够的职位内容,无法进行简历匹配。"
                "请打开完整的招聘职位页面,或选中职位描述文字后再试。"
            )
```

- [ ] **Step 4: Add the continuation branch to `build_prompt`**

In `build_prompt`, immediately after the `section_lines = ...` assignment and before the `return "\n".join([...])`, insert:

```python
        cv = self._resolve_cv_text(cv_text)[:MAX_CV_CHARS]
        if task.prior_result and task.prior_result.strip():
            # 续跑:基于阶段一分析 + 简历生成,不带页面正文。
            return "\n".join(
                [
                    *section_lines,
                    "",
                    "# 我的简历",
                    cv,
                    "",
                    "# 前序匹配分析(基于它来写,不要重复输出它)",
                    task.prior_result.strip(),
                ]
            )
```

Then change the existing stage-1 `return` to reuse `cv` instead of re-resolving — replace the line
`                self._resolve_cv_text(cv_text)[:MAX_CV_CHARS],`
with
`                cv,`.

- [ ] **Step 5: Make `run` merge on continuation**

Replace `run` (currently lines 166-169) with:

```python
    def run(self, task: TaskCreate, cv_text: str | None = None) -> str:
        system = self.system_prompt + "\n\n" + language_directive(task.lang)
        prompt = self.build_prompt(task, cv_text=cv_text)
        output = self.complete(system, prompt, tier=self._router.pick(len(prompt)))
        if task.prior_result and task.prior_result.strip():
            # 把阶段二输出拼到阶段一分析之后,使返回值即「合并全量文本」;
            # service/build_sections 因此无需感知 prior_result。
            return task.prior_result.rstrip() + "\n\n" + output
        return output
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd gateway && uv run pytest tests/test_job_match.py -v`
Expected: PASS (all, including the existing suite).

- [ ] **Step 7: Commit**

```bash
git add gateway/app/agents/job_match.py gateway/tests/test_job_match.py
git commit -m "feat(job_match): on-demand continuation via prior_result"
```

---

## Task 4: job_match `actions()`

**Files:**
- Modify: `gateway/app/agents/job_match.py` (import `Action`; add `actions` method)
- Test: `gateway/tests/test_job_match.py`

**Interfaces:**
- Consumes: `Action` (Task 1); `DEFAULT_SECTIONS`.
- Produces: `JobMatchAgent.actions(task: TaskCreate, lang: str) -> list[Action]`.
  - Stage-1 (no `prior_result`, `cover_letter` not requested) → one `generate_cover_letter` action with `sections=["cover_letter","resume_tips"]`, label zh/en by `lang`.
  - Otherwise → `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `gateway/tests/test_job_match.py`:

```python
def test_actions_offers_cover_letter_on_stage_one():
    agent = JobMatchAgent()
    acts = agent.actions(make_task(), "zh")
    assert len(acts) == 1
    assert acts[0].id == "generate_cover_letter"
    assert acts[0].sections == ["cover_letter", "resume_tips"]
    assert "求职信" in acts[0].label


def test_actions_label_english():
    agent = JobMatchAgent()
    acts = agent.actions(make_task(), "en")
    assert "cover letter" in acts[0].label.lower()


def test_actions_empty_on_continuation():
    agent = JobMatchAgent()
    assert agent.actions(make_continue_task(), "zh") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gateway && uv run pytest tests/test_job_match.py -k actions -v`
Expected: FAIL — `AttributeError: 'JobMatchAgent' object has no attribute 'actions'`.

- [ ] **Step 3: Import `Action` and implement `actions`**

Change the schema import at the top of `gateway/app/agents/job_match.py` (line 8) from:

```python
from app.modules.task.schema import Section, TaskCreate
```

to:

```python
from app.modules.task.schema import Action, Section, TaskCreate
```

Add this method to `JobMatchAgent` (e.g. after `build_sections`):

```python
    def actions(self, task: TaskCreate, lang: str) -> list[Action]:
        """阶段一结果上提供「生成求职信」按钮;续跑/已点名 cover_letter 时不提供。"""
        if task.prior_result and task.prior_result.strip():
            return []
        requested = task.sections or DEFAULT_SECTIONS
        if "cover_letter" in requested:
            return []
        label = "✍️ Write cover letter" if lang == "en" else "✍️ 生成求职信"
        return [
            Action(
                id="generate_cover_letter",
                label=label,
                sections=["cover_letter", "resume_tips"],
            )
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gateway && uv run pytest tests/test_job_match.py -k actions -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add gateway/app/agents/job_match.py gateway/tests/test_job_match.py
git commit -m "feat(job_match): declare generate_cover_letter follow-up action"
```

---

## Task 5: Wire `actions` into the task response

**Files:**
- Modify: `gateway/app/modules/task/service.py:94-107` (TaskResponse construction)
- Test: `gateway/tests/test_job_match_service.py` (create)

**Interfaces:**
- Consumes: `agent.actions(task, lang)` (Task 4), `TaskResponse.actions` (Task 1).
- Produces: `TaskResponse.actions` populated from the agent when it exposes `actions`.

- [ ] **Step 1: Write the failing test**

Create `gateway/tests/test_job_match_service.py`:

```python
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


def job_task() -> TaskCreate:
    return TaskCreate(
        url="https://x.com/j",
        title="Senior Go Engineer",
        page_text="We need Go, Kubernetes and 5 years of distributed systems backend.",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && uv run pytest tests/test_job_match_service.py -v`
Expected: FAIL — `resp.actions` is `[]` for stage one (assertion fails on the list compare).

- [ ] **Step 3: Populate `actions` in `service.run`**

In `gateway/app/modules/task/service.py`, inside `run`, just before `response = TaskResponse(` (currently line 94), add:

```python
            actions = (
                agent.actions(task, task.lang)
                if hasattr(agent, "actions")
                else []
            )
```

Then add `actions=actions,` to the `TaskResponse(...)` constructor (next to `sections=sections,`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gateway && uv run pytest tests/test_job_match_service.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full gateway suite**

Run: `cd gateway && uv run pytest -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add gateway/app/modules/task/service.py gateway/tests/test_job_match_service.py
git commit -m "feat(task): expose agent follow-up actions in the response"
```

---

## Task 6: Extension `buildTaskBody` helper (pure, tested)

**Files:**
- Modify: `extension/auth.js`
- Test: `extension/auth.test.js`

**Interfaces:**
- Produces: `buildTaskBody(payload, opts) -> object` where `opts = { agent, lang, sections?, priorResult? }`. Always spreads `payload` and sets `agent`, `lang`; includes `sections` / `priorResult` only when provided (truthy).

- [ ] **Step 1: Write the failing tests**

Append to `extension/auth.test.js` (and add `buildTaskBody` to its import list from `./auth.js`):

```js
test("buildTaskBody sets agent/lang and spreads payload", () => {
  const body = buildTaskBody(
    { url: "u", pageText: "p" },
    { agent: "job_match", lang: "zh" }
  );
  assert.equal(body.url, "u");
  assert.equal(body.pageText, "p");
  assert.equal(body.agent, "job_match");
  assert.equal(body.lang, "zh");
  assert.equal("sections" in body, false);
  assert.equal("priorResult" in body, false);
});

test("buildTaskBody includes sections and priorResult when given", () => {
  const body = buildTaskBody(
    { url: "u" },
    { agent: "job_match", lang: "en", sections: ["cover_letter", "resume_tips"], priorResult: "ANALYSIS" }
  );
  assert.deepEqual(body.sections, ["cover_letter", "resume_tips"]);
  assert.equal(body.priorResult, "ANALYSIS");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd extension && npm test`
Expected: FAIL — `buildTaskBody is not a function` / import is undefined.

- [ ] **Step 3: Implement `buildTaskBody` in `auth.js`**

Add to `extension/auth.js` (near `taskUrl`):

```js
// Build the JSON body for a /tasks request. `opts.sections` / `opts.priorResult`
// are the on-demand follow-up fields (omitted entirely for the stage-one request).
export function buildTaskBody(payload, { agent, lang, sections, priorResult } = {}) {
  const body = { ...payload, agent, lang };
  if (sections) body.sections = sections;
  if (priorResult) body.priorResult = priorResult;
  return body;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd extension && npm test`
Expected: PASS (existing auth tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add extension/auth.js extension/auth.test.js
git commit -m "feat(ext): pure buildTaskBody helper for task requests"
```

---

## Task 7: Extension dumb-shell — action buttons + continuation handler

**Files:**
- Modify: `extension/background.js` (import `buildTaskBody`; refactor stage-1 fetch into `dispatchTask`; add `AGENT_BRIDGE_CONTINUE` listener; render action buttons + CSS in `renderPanel`)

**Interfaces:**
- Consumes: `buildTaskBody` (Task 6); gateway `TaskResponse.actions` (Task 5).
- Behavior:
  - Stage-1 result `showResult` payload now also carries `agent`, `lang`, `result` (raw), `actions`.
  - `renderPanel` renders one `.ab-action` button per `payload.actions` (result state only).
  - Click → `chrome.runtime.sendMessage({type:"AGENT_BRIDGE_CONTINUE", sections, priorResult, lang, url, agent})` with a response callback; button shows loading.
  - Background `AGENT_BRIDGE_CONTINUE` listener POSTs `/tasks` with `sections`+`priorResult`; on success re-injects the full panel; on failure `sendResponse({ok:false})` so the page re-enables the button inline.

> No automated DOM/SW test harness exists for `background.js`; this task ends with a scripted manual verification.

- [ ] **Step 1: Import the helper**

In `extension/background.js`, add `buildTaskBody` to the import from `./auth.js` (lines 1-10):

```js
import {
  buildAuthHeaders,
  buildTaskBody,
  taskUrl,
  shouldClearToken,
  handleExternalMessage,
  TOKEN_KEY,
  EXPIRES_KEY,
  GATEWAY_KEY,
  DEFAULT_GATEWAY,
} from "./auth.js";
```

- [ ] **Step 2: Extract a shared `dispatchTask` and call it from the context handler**

Replace the body of the `chrome.runtime.onMessage.addListener` for `AGENT_BRIDGE_CONTEXT` (the `Promise.all([...]).then(...)` network block, currently ~lines 127-196) so that after building `payload` it delegates to a new shared function. Concretely, replace from `showResult(tabId, { state: "loading", ... });` through the end of that listener with:

```js
  showResult(tabId, { state: "loading", source: message.payload && message.payload.url });

  resolveLang().then((lang) =>
    dispatchTask({
      tabId,
      lang,
      agent,
      source: (message.payload && message.payload.url) || "",
      body: (token) =>
        buildTaskBody(payload, { agent, lang }),
    })
  );
});

// Shared task dispatch: builds the request, handles token/timeout/keep-alive,
// renders the result panel. Used by both the stage-one context flow and the
// on-demand continuation flow. `opts.body(token)` returns the JSON body object.
function dispatchTask({ tabId, lang, agent, source, body, onError }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  const keepAlive = setInterval(
    () => chrome.runtime.getPlatformInfo(() => {}),
    20000
  );
  const done = () => {
    clearTimeout(timeout);
    clearInterval(keepAlive);
  };

  return getGatewayConfig()
    .then(({ base, token }) =>
      fetch(taskUrl(base), {
        method: "POST",
        headers: buildAuthHeaders(token),
        body: JSON.stringify(body(token)),
        signal: controller.signal,
      }).then((response) => {
        if (shouldClearToken(response.status)) {
          chrome.storage.local.remove([TOKEN_KEY, EXPIRES_KEY]);
          done();
          showResult(tabId, {
            state: "error",
            source,
            errorHint:
              "登录已过期或扩展被解绑,请在网页端重新登录并连接扩展。",
            text: "Agent Bridge: 请在网页端重新登录并连接扩展。",
          });
          return null;
        }
        return response.json();
      })
    )
    .then((task) => {
      if (!task) return false; // 401 已处理
      done();
      showResult(tabId, {
        state: "result",
        html: task.result_html,
        sections: task.sections || [],
        actions: task.actions || [],
        agent,
        lang,
        result: task.result || "",
        text: task.result || task.detail || "(no result)",
        source: (task.request && task.request.url) || source,
        durationMs: task.duration_ms,
      });
      return true;
    })
    .catch((error) => {
      done();
      console.error("[Agent Bridge] gateway request failed:", error);
      if (onError) {
        onError(error);
        return false;
      }
      const hint =
        error.name === "AbortError"
          ? "请求超时,网关无响应。"
          : "无法连接网关 (" + error.message + ")。";
      showResult(tabId, {
        state: "error",
        source,
        errorHint: hint,
        errorCmd: "./dev-start backend",
        text: "Agent Bridge 出错:" + hint,
      });
      return false;
    });
}
```

(Keep the existing `resolveLang` and `getGatewayConfig` functions. The `payload` variable is still built earlier in the same listener from `message.payload` + selection snapshot.)

- [ ] **Step 3: Add the continuation listener**

Add a new listener (e.g. right after the context listener / `dispatchTask` definition):

```js
// On-demand follow-up (e.g. 生成求职信). The panel button sends the stage-1
// raw result back as priorResult; we re-POST /tasks for the named sections and
// re-render the full merged panel. On failure we reply {ok:false} so the page
// re-enables its button and keeps the stage-1 result visible.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "AGENT_BRIDGE_CONTINUE" || !sender.tab) return;
  const tabId = sender.tab.id;

  dispatchTask({
    tabId,
    lang: message.lang,
    agent: message.agent,
    source: message.url || "",
    body: () =>
      buildTaskBody(
        { url: message.url || "" },
        {
          agent: message.agent,
          lang: message.lang,
          sections: message.sections,
          priorResult: message.priorResult,
        }
      ),
    onError: () => sendResponse({ ok: false }),
  }).then((ok) => {
    if (ok) sendResponse({ ok: true });
    else sendResponse({ ok: false });
  });

  return true; // async sendResponse
});
```

- [ ] **Step 4: Render action buttons in `renderPanel`**

4a. Add CSS for the action button. In the `style.textContent` template, after the `.sec-body` rules (around line 412), add:

```css
    .ab-actions { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
    .ab-action { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 12px; background: var(--signal-soft); color: var(--signal); border: 1px solid var(--signal); border-radius: 8px; font-size: 13.5px; font-weight: 600; cursor: pointer; }
    .ab-action:hover { filter: brightness(1.12); }
    .ab-action:disabled { opacity: .6; cursor: default; }
    .ab-action-err { margin-top: 8px; color: var(--alert); font-size: 12.5px; }
```

4b. Render the buttons. In `renderPanel`, find the result branch that calls `renderSections(body, payload.sections);` (around line 522-523). Immediately after that call, add:

```js
    if (payload.actions && payload.actions.length) {
      const actionsWrap = el("div", "ab-actions");
      payload.actions.forEach((action) => {
        const btn = el("button", "ab-action");
        btn.type = "button";
        btn.textContent = action.label;
        const err = el("div", "ab-action-err");
        err.style.display = "none";
        btn.addEventListener("click", () => {
          btn.disabled = true;
          const original = action.label;
          btn.textContent = payload.lang === "en" ? "Generating…" : "生成中…";
          err.style.display = "none";
          chrome.runtime.sendMessage(
            {
              type: "AGENT_BRIDGE_CONTINUE",
              sections: action.sections,
              priorResult: payload.result,
              lang: payload.lang,
              url: payload.source,
              agent: payload.agent,
            },
            (resp) => {
              // 成功时后台已整面板重渲染,这里不必处理;失败时恢复按钮并提示。
              if (!resp || !resp.ok) {
                btn.disabled = false;
                btn.textContent = original;
                err.textContent =
                  payload.lang === "en"
                    ? "Generation failed, please retry."
                    : "生成失败,请重试。";
                err.style.display = "block";
              }
            }
          );
        });
        actionsWrap.append(btn, err);
      });
      body.append(actionsWrap);
    }
```

- [ ] **Step 5: Lint-check the bundle loads (syntax)**

Run: `cd extension && node --check background.js`
Expected: no output (exit 0) — file parses.

- [ ] **Step 6: Manual verification (load unpacked)**

1. `chrome://extensions` → Developer mode → Load unpacked → select `extension/`.
2. Ensure the gateway is running and the extension is connected (token present).
3. Open a real job posting page. Right-click → "Agent Bridge: 分析与简历匹配".
4. **Expect:** panel shows 结论(lede) + 业务介绍 + 技能匹配 only, and a "✍️ 生成求职信" button at the bottom. No 求职信 / 简历更新建议 yet.
5. Click "✍️ 生成求职信". Button shows "生成中…".
6. **Expect:** panel re-renders WITH 求职信 + 简历更新建议 appended after 技能匹配; 结论 still on top; 求职信 has a 复制 button.
7. Stop the gateway, repeat steps 3-5. **Expect:** the stage-1 panel stays visible, the button re-enables, and "生成失败,请重试。" appears under it.

- [ ] **Step 7: Commit**

```bash
git add extension/background.js
git commit -m "feat(ext): dumb-shell action buttons + on-demand continuation flow"
```

---

## Self-Review

**Spec coverage:**
- Generic rubric → Task 2 (Step 3 + `test_conclusion_rubric_is_generic`). ✓
- Generation ≠ display order → Task 2 (`GENERATION_ORDER`/`DISPLAY_ORDER`, re-sort, ordering tests). ✓
- Default sections = analysis only → Task 2 (`DEFAULT_SECTIONS`, `test_default_prompt_has_analysis_only`). ✓
- `sections` + `prior_result` contract → Task 1 (schema) + Task 3 (build_prompt/validate/run). ✓
- Continuation generates from prior_result + CV, no page text → Task 3. ✓
- Merge in `agent.run` so service stays generic → Task 3 Step 5 + Task 5. ✓
- `actions` declared by backend, rendered by dumb shell → Task 4 (agent) + Task 5 (service) + Task 7 (render). ✓
- No DB / no persistence change / no ownership check → confirmed: `repo.py`/`api.py` untouched; service change is actions-only. ✓
- Extension echoes prior_result back, fails gracefully keeping stage-1 visible → Task 7 Steps 3-4, 6. ✓
- Future tailored_resume reserved → adding an id to the three constants + an `Action`; no code blocks needed now (documented in spec "不在本期范围"). ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `Action(id,label,sections)` consistent across Tasks 1/4/5/7; `buildTaskBody(payload, {agent,lang,sections,priorResult})` consistent Tasks 6/7; `prior_result` (snake, alias `priorResult`) consistent schema↔agent, `priorResult` on the wire consistent extension↔alias. `dispatchTask` returns a Promise<boolean> consumed by the continuation listener. ✓

## Execution Handoff

Plan complete. See "Two execution options" below.
