# 求职匹配：按需分阶段 + 通用评分（job_match on-demand sections）设计

日期：2026-06-23

## 背景与目标

现状：`job_match` 一次 `POST /tasks` 调用即生成全部 5 个区块
（`conclusion / overview / skills / cover_letter / resume_tips`），
生成顺序就是展示顺序（`SECTION_SPECS` 的排列），`conclusion` 的评分提示词里
写死了某次调试用的具体行业/技能（AI/LLM、「12 年 vs 1-3 年」），不通用。

三个目标：

1. **通用化评分**：`conclusion` 的匹配分要 JD 无关、克制、与 `skills` 自洽，
   不再出现任何写死的行业/技能名。
2. **生成顺序 ≠ 展示顺序**：模型先写 `skills` 再写 `conclusion`，让评分被技能匹配
   锚定；后端把区块重排成「`conclusion` 置顶」再回前端，前端渲染逻辑不变。
3. **求职信/简历建议按需生成**：右键默认只跑「匹配分析」三块；用户觉得合适后，
   点面板里的「✍️ 生成求职信」按钮，才生成 `cover_letter + resume_tips`。

延伸愿景（**本期不实现**，但契约要能容纳）：未来基于 JD + 真实数据直接生成一份
「定制简历」，届时只是后端多加一个 section + 一个 action，扩展不用改、不用重新发版。

## 核心思路

阶段二**不依赖 DB、不缓存、不改隐私留存**：前端本就持有阶段一的 `result` 文本，
点按钮时把它作为参数原样回传。后端按登录用户重解析 CV，用「阶段一分析 + CV」生成
阶段二区块，再把「阶段一文本 + 阶段二输出」拼起来重新切块，返回**合并好的全量区块**，
前端整体替换面板。由此：

- 不查 `task_records` → 开源无 DB 模式照常可用；
- 不默认落库 `result` → 隐私姿态不变；
- 用户只能回传自己的数据 → 无多租户越权面；
- 数据随消息走 → 抗 MV3 service worker 重启，扩展不需要本地状态。

代价仅为阶段一分析文本（几 KB）随阶段二请求回传一趟，可忽略。

## API 契约

阶段二复用同一个 `POST /tasks`，**不新增端点**。

`TaskCreate` 新增两个可选字段（仅 `job_match` 读取，其余 agent 无视）：

```python
sections: list[str] | None = Field(default=None)            # 省略 = 默认分析集
prior_result: str | None = Field(default=None, max_length=50_000)  # 续跑时回传的阶段一 result
```

`TaskResponse` 新增 `actions`——后端声明「当前结果上可触发哪些后续动作」，
前端照单渲染按钮，未来新动作纯后端添加：

```python
class Action(BaseModel):
    id: str               # "generate_cover_letter"
    label: str            # "✍️ 生成求职信" / "✍️ Write cover letter"（按 lang）
    sections: list[str]   # ["cover_letter", "resume_tips"]

class TaskResponse(BaseModel):
    ...
    actions: list[Action] = Field(default_factory=list)
```

### 阶段一（右键，`sections` 省略，`prior_result` 为空）

- 生成 `conclusion + overview + skills`。
- 返回 `actions = [Action(id="generate_cover_letter", label=<按 lang>, sections=["cover_letter","resume_tips"])]`。
- 其它 agent（如 `summary_page`）`actions = []`。

### 阶段二（点「生成求职信」）

- 请求：`POST /tasks`，`sections=["cover_letter","resume_tips"]`，
  `prior_result=<阶段一 result 文本>`，仍带 `agent="job_match"`、`url`、`lang`。
  （`url` 仅用于落库指标/日志，页面正文可不传。）
- 后端用「`prior_result` + 重解析的 CV」生成阶段二区块。
- 返回合并后的全量 `sections`（见下）+ `actions=[]`。

## 区块目录与三组顺序

把扁平的 `SECTION_SPECS` 改造为「目录 + 三组顺序常量」。`SECTION_META`
（展示标题/copyable/collapsible）保留。

```python
# 所有区块的生成指令（id -> instruction）
SECTION_INSTRUCTIONS = {
    "conclusion":   "...(通用评分标尺，见下)...",
    "overview":     "...(同现状)...",
    "skills":       "...(同现状，已带 HR 视角)...",
    "cover_letter": "...(同现状，已带 HR 视角)...",
    "resume_tips":  "...(同现状，已带 HR 视角)...",
}

DEFAULT_SECTIONS = ["conclusion", "overview", "skills"]                       # 右键默认集
GENERATION_ORDER = ["overview", "skills", "conclusion",
                    "cover_letter", "resume_tips"]                            # 喂模型：skills 在 conclusion 前
DISPLAY_ORDER    = ["conclusion", "overview", "skills",
                    "cover_letter", "resume_tips"]                           # 回前端：conclusion 置顶
```

- `build_prompt` 把「被请求的区块」按 `GENERATION_ORDER` 排序后逐条拼
  `@@SECTION {sid} — {instruction}`。
- `build_sections` 解析模型输出后，按 `DISPLAY_ORDER` 重排再返回（前端无感知，
  仍是 conclusion 当 lede）。未识别的 id 排在末尾、稳定保序。
- 未来「定制简历」= 往三个常量各加一行 + 写 `tailored_resume` 指令。

## 通用评分标尺（`conclusion` 指令，去掉写死的行业/技能）

要点（JD 无关）：

- 一句话同时给出 ①该职位所属行业 + 具体业务；②匹配分（0-100）。
- 评分克制、真实、不给安慰分，且与 `skills` 的 ✅/⚠️/❌ 自洽。
- 先识别该岗位「反复强调、决定能否胜任的硬性核心要求」（而非人人都有的通用项），
  按核心要求命中情况打分：
  - 核心要求出现 ❌ 缺失 → 不应高于 65；
  - 多项核心要求仅 ⚠️ 部分满足 → 不应高于 75；
  - 核心要求基本命中、仅边角缺口 → 80+；
  - 几乎全部命中 → 90+。
- 通用基础技能再强也不能补偿核心要求缺失；经验年限明显超标则点明可能「资历过高」。
- 只输出这一句。

## 组件与改动

### `app/agents/job_match.py`

- `SECTION_SPECS` → `SECTION_INSTRUCTIONS` + `DEFAULT_SECTIONS` / `GENERATION_ORDER` /
  `DISPLAY_ORDER`。
- `conclusion` 指令换成上面的通用标尺。
- `_requested_sections(task)`：返回 `task.sections` 经校验/去重后的集合，
  空则回 `DEFAULT_SECTIONS`；过滤掉不在目录里的 id。
- `validate(task)`：
  - 续跑模式（`task.prior_result` 非空）→ 要求 `prior_result` 去空白后非空，
    **跳过**「页面正文 ≥ `MIN_JOB_CONTENT_CHARS`」检查；
  - 否则 → 沿用现有的页面正文长度检查。
- `build_prompt(task, cv_text=None)`：
  - 续跑模式：prompt = 「前序分析(prior_result) + 我的简历(CV) + 请输出被请求区块」，
    **不含**页面正文；
  - 阶段一模式：同现状（简历 + 页面信息），区块取 `_requested_sections` 并按
    `GENERATION_ORDER` 排序。
- `run(task, cv_text=None)`：续跑模式下（`task.prior_result` 非空），把模型输出
  **拼接到 `prior_result` 之后**再返回，使 `run()` 的返回值就是「合并后的全量文本」。
  这样 service 层与 `build_sections` 完全不必感知 `prior_result`，合并逻辑收敛在 agent 内。
  ```python
  output = self.complete(system, prompt, tier=...)
  if task.prior_result and task.prior_result.strip():
      return task.prior_result.rstrip() + "\n\n" + output
  return output
  ```
- `build_sections(result, lang)`：解析后按 `DISPLAY_ORDER` 重排（未识别 id 稳定排末尾）。
  续跑时 `result` 已是合并文本（含 5 个 `@@SECTION` 标记）→ 一次切出全量区块。
- 新增 `actions(task, lang) -> list[Action]`：阶段一（无 `prior_result` 且默认集）
  返回「生成求职信」动作；续跑返回 `[]`。label 按 `lang` 中英切换。

### `app/modules/task/schema.py`

- `TaskCreate` 加 `sections`、`prior_result`（带 `max_length`）。
- 新增 `Action` 模型；`TaskResponse` 加 `actions`。

### `app/modules/task/service.py`

- 唯一改动：构造 `TaskResponse` 时，若 `hasattr(agent, "actions")` 则调用
  `agent.actions(task, task.lang)` 填入 `TaskResponse.actions`。
- 合并逻辑已收敛在 `agent.run()`（见上），service 的 `build_sections` 调用与落库
  逻辑**保持原样**——续跑模式下 `result` 即合并文本，`result_html`/`sections` 自然全量。
- 限流、CV 解析、debug 落库等其余逻辑不变。**`repo.py`/`api.py` 不改。**

### `extension/background.js`（一次性改成「哑壳」，之后新功能不再动它）

- `showResult` 的结果 payload 带上 `agent`、`result`（阶段一文本）、`actions`。
- `renderPanel`：结果态下，按 `payload.actions` 渲染按钮（本期只有「生成求职信」）。
  点击 → `chrome.runtime.sendMessage({type:"AGENT_BRIDGE_CONTINUE", sections, priorResult, lang, url, agent})`，
  按钮转 loading。
- 新增 `onMessage` 处理 `AGENT_BRIDGE_CONTINUE`：用现有 `getGatewayConfig`/`buildAuthHeaders`
  打同一个 `/tasks`（body 带 `sections` + `prior_result`），复用现有超时/keep-alive/
  401 清 token 逻辑；成功后 `showResult` 用返回的合并 `sections`/`result_html` 重渲染。
- 失败/超时/token 过期：沿用现有错误处理，阶段一结果保持可见。
- **不引入** `storage.session`、不保存任何阶段一状态：上下文随消息从面板回传。

> 注：`action` 本期固定打 `/tasks`、只带 `sections`。未来若拆分 URL，再给 `action`
> 加一个目标 `path` 字段由壳照打即可，仍是纯后端改动、扩展不重新发版。

## 测试（`gateway/tests/test_job_match.py` 为主）

- `build_prompt` 默认集：含 `@@SECTION conclusion/overview/skills`，
  **不含** `cover_letter/resume_tips`。
- `build_prompt` 指定 `sections=["cover_letter","resume_tips"]` + `prior_result`：
  只含这两块，含 `prior_result` 文本、**不含**页面正文。
- 生成顺序：prompt 中 `skills` 的 `@@SECTION` 行出现在 `conclusion` 之前。
- `build_sections` 展示顺序：即便模型先输出 `skills` 再 `conclusion`，返回的区块
  仍是 `conclusion` 在前。
- 续跑合并：`prior_result`(含 conclusion/overview/skills) + 阶段二输出
  (cover_letter/resume_tips) 拼接后切块 → 得到全量 5 块、按 DISPLAY_ORDER。
- `validate`：有 `prior_result` 时空页面正文也通过；`prior_result` 为空白则报错。
- 未知 section id 被过滤、不报错。
- `actions()`：阶段一返回含 `generate_cover_letter`；续跑返回空。
- 现有用例（5 个区块标题、解析、无标记兜底）保持通过。

## 验收标准

1. 右键「分析与简历匹配」只展示 结论/业务介绍/技能匹配 三块，底部有「✍️ 生成求职信」按钮。
2. 点按钮后，面板追加「求职信」「简历更新建议」两块，结论仍在最上。
3. 匹配分对「核心要求缺失」的职位明显走低（不再无脑 85-95），且与技能表自洽；
   提示词中无任何写死的具体行业/技能。
4. 全程不依赖 DB；服务端不新增页面正文/result 的默认落库。
5. `gateway` 测试全绿。

## 不在本期范围

- 「定制简历」生成（仅预留 `sections`/`actions` 扩展位）。
- URL 拆分 / REST 化端点。
