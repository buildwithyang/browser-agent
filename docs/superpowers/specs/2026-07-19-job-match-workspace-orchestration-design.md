# Job Match Workspace Orchestration Design

日期：2026-07-19

状态：设计已确认，实施计划已完成、待执行。本设计只描述目标实现，不表示云端网关或 Chrome 扩展已经发布。2026-07-20 增加严格的 Extension 协议版本门。

## 1. 目标

把 LinkedIn / Indeed Workspace 从“选择 Action 就强制生成对应文档”改为经典的多轮聊天工作台：

- 一个网页对应一个 Workspace。
- 所有 Action 共享同一份完整聊天历史。
- Action 是当前意图的强提示，不是强制执行命令。
- `JobMatchAgent` 作为 Orchestrator，根据当前消息、Action、历史和已有 Artifact 选择专业子 Agent。
- 普通回答和正式产物使用不同的结构化结果。
- 正式产物作为 Assistant Message 的 Attachment 出现在时间线中。
- Quick Insight 和 Workspace 使用独立的调用路径、Prompt 和输出契约。

整体流程：

```text
Right Click
  → Quick Insight
  → Action
  → Shared Workspace
  → Shared History
  → Follow-up
```

本设计替代 `2026-07-18-shared-workspace-design.md` 中以下内容：

- `currentDocument` / `document` 单产物模型。
- Action 直接决定生成内容的执行模型。
- Workspace 内展示完整 Quick Insight 卡片。
- Workspace 文档由后端返回 HTML 的契约。

Workspace 身份、`resourceUrl` 规范化、按用户隔离的本地存储以及 10 条输入消息限制继续沿用原设计。

## 2. 本期边界

本期实现：

- Job Match Workspace 的 Orchestrator 与四个专业子 Agent。
- Action 作为意图提示的多轮聊天。
- Quick Insight Action 的直接执行路径。
- `reply`、`create_artifact`、`update_artifact` 三种结果。
- Message Attachments 与多类型最新 Artifacts。
- Assistant Markdown 渲染、消息时间和经典聊天布局。
- Cover Letter 的本地历史版本。
- CV 固定测试网页预览。
- Gateway 与 Extension 的协议版本握手及更新提示。

本期不实现：

- 服务端 Chat Thread 或跨设备历史恢复。
- 服务端 Artifact 表、Repository 或版本 API。
- CV 私有托管、签名 URL 和可访问的历史版本。
- 文件、图片 Attachment 的实际生成与渲染。
- Mock Interview、Salary、Company Research 等后续子 Agent。
- 页面正文变化检测。
- 未上线的 `DocumentContent` Workspace 契约兼容层。
- 旧 `/tasks` 的 Agent 生成逻辑；该入口仅保留升级提示。

普通网页继续由 `SummaryPageAgent` 处理，并只展示 `Ask More`。本期多 Agent 编排只作用于 LinkedIn / Indeed 的 Job Match Workspace。

## 3. 核心概念

### 3.1 Action

Action 表示用户当前选择的任务方向：

- `analyze`
- `tailor_resume`
- `write_cover_letter`
- `ask_more`

Workspace 输入框附近的 Action 是强意图提示。最终行为优先级固定为：

```text
当前用户消息 > 当前 Action > 完整历史 > GeneralQA 默认能力
```

例如，用户选择 `Tailor Resume` 后询问“我的哪段经历最值得突出？”，应由 Resume 子 Agent 给出建议，不应立即生成简历。只有“根据刚才的分析生成一版简历”这类明确要求才生成正式 CV。

### 3.2 Artifact

Artifact 是可继续修改的正式产物。本期只有：

- `cv`
- `cover_letter`

Workspace 同时保存每种 Artifact 的最新版本，不再只有一个 `currentDocument`。切换 Action 不会删除或覆盖另一种 Artifact。

### 3.3 Attachment

Attachment 是某一次 Assistant Message 中的产物快照，用于时间线展示：

- `type=cv`：`content` 是 CV 预览 URL。
- `type=cover_letter`：`content` 是可渲染、可复制的求职信 Markdown。

历史 Message 和 Attachment 记录本身都不可变。更新 Artifact 时追加一条新的 Assistant Message，不修改旧消息。该规则是 Task Service reducer 与 Extension 的状态转换不变量；由于服务端不保存 Thread，旧 state 每次仍按不可信客户端输入重新校验，并不构成服务端持久化保证。Cover Letter Attachment 的正文是真正的历史快照；CV Attachment 本期虽然记录版本，但固定 URL 的目标内容不是版本化快照。

未来可以扩展：

- `type=file`：`content` 是下载 URL。
- `type=image`：`content` 是图片 URL。

这些类型只保留扩展方向，本期 API 校验不接受尚未实现的类型。

## 4. 交互语义

### 4.1 Workspace Action

用户在 Workspace 内选中 Action 并发送消息时，走完整 Orchestrator：

```text
User Message + Selected Action + Histories + Artifacts
  → IntentRouter
  → Specialist Agent
  → JobMatchAgent validates result
  → reply / create_artifact / update_artifact
```

Action 不创建新会话、不清空历史，也不直接规定结果类型。

### 4.2 Quick Insight Action

Quick Insight 的 Action 是用户从页面浮层发出的明确任务命令，语义与 Workspace Action 不同：

- `Analyze`：打开 Workspace，直接调用 `JobAnalysisAgent`，并生成一条普通回复。
- `Tailor Resume`：打开 Workspace，直接调用 `ResumeTailoringAgent`，并创建或更新 CV Artifact。
- `Generate Cover Letter`：打开 Workspace，直接调用 `CoverLetterAgent`，并创建或更新 Cover Letter Artifact。
- `Ask More`：只打开 Workspace、选中输入框，不调用 Agent。

前三个 Action 使用确定性映射，跳过 `IntentRouter`，避免无必要的额外模型调用。生成结果直接成为一条 Assistant Message，不伪造 User Message。

若同一 Workspace 已有历史和 Artifact，Quick Insight Action 必须携带并使用现有 `histories + artifacts`。已有同类型 Artifact 时生成 `update_artifact`，否则生成 `create_artifact`。该路径允许历史中出现连续的 Assistant Message。

该确定性路径还必须校验 Specialist 结果：

- Analyze 只接受 `reply`。
- Tailor Resume 只接受 CV `artifact_draft`。
- Generate Cover Letter 只接受 Cover Letter `artifact_draft`。
- 任何其他结果均返回 502，Workspace 状态保持不变。

## 5. 架构

采用以下模式：

- **Facade / Mediator**：`JobMatchAgent` 对 Task Service 暴露稳定入口，协调路由和专业子 Agent。
- **Strategy**：每个专业子 Agent 实现相同的聊天策略接口，可以独立替换和测试。
- **Router**：`IntentRouter` 只做意图分类，不生成最终回答。
- **State Reducer**：Task Service 根据 `ChatResult` 一次性生成经过校验的完整 next histories 与 artifacts。

Quick Insight 与 Workspace 使用两个明确的抽象接口，避免继续用同一个 `execute() -> DocumentContent` 表达不同场景：

```python
class QuickInsightAgent(ABC):
    @abstractmethod
    def quick_insight(self, context) -> AgentExecution[Insight]: ...

    @abstractmethod
    def available_actions(self, context) -> list[Action]: ...


class WorkspaceAgent(ABC):
    @abstractmethod
    def handle_chat(self, context: WorkspaceContext) -> AgentExecution[ChatResult]: ...
```

`JobMatchAgent` 实现两个接口。`SummaryPageAgent` 同样实现 `WorkspaceAgent`，其 `handle_chat()` 只允许 `Ask More` 并只返回 `ReplyResult`；因此普通网页也使用同一个新版 `/tasks/workspace` wire contract，不再从 Workspace 返回 `DocumentContent`。

旧 `POST /tasks` 不再实现第三套 Agent interface，也不再生成 `DocumentContent`。该路由只保留一个 API 层升级门，固定返回 `426 Upgrade Required`；因此新版 Agent 不承担任何 legacy 生成职责，也不需要复制旧 Agent 到 `legacy/`。

```text
TaskService
  └── JobMatchAgent
      ├── quick_insight(context)
      │   └── JobQuickInsightAgent
      ├── available_actions(context)
      └── handle_chat(session, message, selected_action, trigger)
          ├── IntentRouter
          ├── JobAnalysisAgent
          ├── ResumeTailoringAgent
          ├── CoverLetterAgent
          └── GeneralQAAgent
```

建议代码结构：

```text
gateway/app/agents/job_match/
├── __init__.py
├── agent.py
├── context.py
├── quick_insight.py
├── router.py
├── README.md
└── specialists/
    ├── __init__.py
    ├── base.py
    ├── analysis.py
    ├── resume.py
    ├── cover_letter.py
    └── general_qa.py
```

`agents/job_match/README.md` 说明公开接口、目录职责、路由优先级、合法结果矩阵和无状态约束。

### 5.1 JobMatchAgent

公开职责：

```python
class JobMatchAgent:
    def quick_insight(self, context) -> AgentExecution[Insight]: ...
    def available_actions(self, context) -> list[Action]: ...
    def handle_chat(self, context: JobChatContext) -> AgentExecution[ChatResult]: ...
```

`JobChatContext` 是一次请求的不可变上下文，包含 trigger、当前页面、当前用户简历、selected Action、可选当前消息、完整 histories 和最新 artifacts。

它负责：

- 阅读完整历史和最新 Artifacts。
- 根据 `trigger` 选择确定性 Quick Insight Action 路径或普通聊天路径。
- 调用 `IntentRouter` 和一个专业子 Agent。
- 验证子 Agent 的结果类型是否合法。
- 根据已有 Artifact 决定最终是 create 还是 update。
- 返回结构化 `ChatResult`，不创建 UUID、时间戳或本地存储状态。

Agent 保持无状态。用户简历、页面内容、历史和 Artifact 都由请求上下文注入，不能缓存在 Agent 实例中。

### 5.2 IntentRouter

`IntentRouter` 使用一次结构化模型调用输出：

```text
RouteDecision
└── specialist: job_analysis | resume | cover_letter | general_qa
```

Router 只选择 Specialist，不判断 reply/create/update，也不直接生成对用户的回答。当前消息中的明确意图优先于 Action，例如选中 `Ask More` 但输入“帮我生成一封 200 词求职信”，仍路由到 `CoverLetterAgent`。

### 5.3 Specialist Agents

专业子 Agent 使用统一抽象接口：

```python
class JobMatchSpecialist(ABC):
    @abstractmethod
    def handle(self, context: JobChatContext) -> AgentExecution[SpecialistResult]: ...
```

`SpecialistResult` 只有两种候选结果：

```text
SpecialistReply
├── type = reply
└── markdown

ArtifactDraftResult
├── type = artifact_draft
├── markdown
├── artifact_type
├── title
└── draft
```

Specialist 根据用户消息和上下文决定是回答问题还是生成正式草稿；它不判断最终是 create 还是 update。

合法候选结果矩阵：

| Specialist | reply | artifact_draft |
| --- | --- | --- |
| JobAnalysisAgent | 是 | 否 |
| ResumeTailoringAgent | 是 | 是，仅 CV |
| CoverLetterAgent | 是 | 是，仅 Cover Letter |
| GeneralQAAgent | 是 | 否 |

`JobMatchAgent` 必须校验该矩阵，再根据请求中是否已有同类型 Artifact，把 `artifact_draft` 转换成最终的 `create_artifact` 或 `update_artifact`。非法类型、错误 Artifact 类型或缺失 Artifact 内容均视为 Agent 输出失败，不能修改 Workspace。

## 6. ChatResult 契约

Agent 最终结果使用 discriminated union，不再以空文档或 `kind` 字符串隐式表达行为：

```text
ReplyResult
├── type = reply
└── markdown

CreateArtifactResult
├── type = create_artifact
├── markdown                 # Attachment 上方的简短 Assistant 说明
├── artifact_type
├── title
└── draft

UpdateArtifactResult
├── type = update_artifact
├── markdown
├── artifact_type
├── title
└── draft
```

规则：

- `reply` 不携带 Artifact。
- create/update 必须携带完整的新草稿，不返回局部 patch。
- 如果目标类型尚不存在，最终结果必须是 create；已经存在时必须是 update。
- Orchestrator 根据请求中的最新 Artifact 规范化 create/update，避免子 Agent 误判版本状态。
- 每轮最多生成一个 Artifact；同时生成 CV 和 Cover Letter 不在本期范围。
- `markdown` 和 `draft` 都只包含 Markdown，不包含后端生成的 HTML。

## 7. Workspace Wire Contract

### 7.1 Extension 协议版本握手

Extension 与 Gateway 使用独立的整数协议版本，不使用 `manifest.json` 中的发布版本判断 API 兼容性：

```text
CURRENT_EXTENSION_PROTOCOL_VERSION = 2
```

原因是扩展可能只修改 UI 或文案而不改变 wire contract；如果直接比较 `manifest.version`，每次纯前端发布都会错误地强迫 Gateway 和 Extension 同步升级。

Extension 对 `POST /tasks/quick-insight` 和 `POST /tasks/workspace` 的每次请求都发送：

```http
X-Agent-Bridge-Protocol-Version: 2
```

Gateway 通过 Task 协议中间件在路由、鉴权、请求体解析和 Agent 执行前，对两个新版 Task `POST` 做严格相等校验。缺少 Header、无法解析或版本不相等时返回：

```http
HTTP/1.1 426 Upgrade Required
Content-Type: application/json
Upgrade: Agent-Bridge/2
X-Agent-Bridge-Protocol-Version: 2

{
  "code": "extension_update_required",
  "message": "Extension update required",
  "required_protocol_version": 2,
  "update_url": "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
}
```

所有 Task HTTP 响应，包括 2xx、401、429 和 502，都返回 `X-Agent-Bridge-Protocol-Version: 2`；成功的 `QuickInsightResponse` 和 `WorkspaceResponse` 顶层还必须返回 `protocol_version: 2`。Extension 在处理认证错误或业务错误前先校验响应 Header，并在成功时再次校验 JSON 字段。任一版本缺失或不相等都视为协议不兼容，不能清理 token 或把响应写入本地 Workspace。

CORS 位于协议中间件外层，协议中间件位于 Session/Router 外层；`OPTIONS` 预检与非 POST 方法不做版本拦截。CORS 必须允许并暴露协议 Header，确保 Side Panel 能读取响应版本。

协议常量是代码级契约，不能通过运行时环境变量任意改变。更新地址属于部署配置，可由 Gateway Settings 覆盖，默认指向当前 Chrome Web Store 页面；Extension 同时内置同一商店地址，供旧 Gateway 没有返回升级 payload 时兜底。Extension 可以附带 `manifest.version` 做诊断，但它不参与兼容性判断。

### 7.2 Request

`POST /tasks/workspace` 使用 `trigger` 区分两种合法输入。实现时使用 Pydantic discriminated union，避免依靠可空字段组合猜测请求类型。

普通消息：

```json
{
  "trigger": "user_message",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前页面重新采集的 JD",
  "pageText": "当前页面正文",
  "lang": "zh",
  "actionId": "tailor_resume",
  "histories": [],
  "artifacts": {
    "cv": null,
    "cover_letter": null
  },
  "message": "我最应该突出哪段经历？"
}
```

Quick Insight Action：

```json
{
  "trigger": "quick_insight_action",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前页面重新采集的 JD",
  "pageText": "当前页面正文",
  "lang": "zh",
  "actionId": "tailor_resume",
  "histories": [],
  "artifacts": {
    "cv": null,
    "cover_letter": null
  }
}
```

`user_message` 必须携带非空 `message`；`quick_insight_action` 禁止携带 `message`。`ask_more` 不发送 Quick Insight Action 请求。

### 7.3 HistoryMessage

```json
{
  "id": "message-uuid",
  "role": "assistant",
  "content": "已生成一版更贴合该岗位的求职信。",
  "action_id": "write_cover_letter",
  "created_at": "2026-07-19T10:24:31Z",
  "attachments": [
    {
      "id": "attachment-uuid",
      "artifact_id": "artifact-uuid",
      "version": 1,
      "type": "cover_letter",
      "title": "Cover Letter",
      "content": "Dear Hiring Manager, ..."
    }
  ]
}
```

所有 Message 都有服务端生成的 `id` 和 UTC `created_at`。`attachments` 始终是数组；普通回复和 User Message 使用空数组。

`action_id` 记录用户本轮选择或 Quick Insight 入口的 Action，便于还原交互，但不代表最终实际选择的 Specialist。本期只有 Assistant Message 可以包含 Attachment；用户上传文件或图片不在范围内。

### 7.4 Artifact

```json
{
  "id": "artifact-uuid",
  "type": "cover_letter",
  "version": 1,
  "title": "Cover Letter",
  "draft": "Dear Hiring Manager, ...",
  "attachment": {
    "id": "attachment-uuid",
    "artifact_id": "artifact-uuid",
    "version": 1,
    "type": "cover_letter",
    "title": "Cover Letter",
    "content": "Dear Hiring Manager, ..."
  }
}
```

`artifacts` 是固定键、可空值的对象，每个非空值都是该类型的最新 Artifact：

```json
{
  "cv": null,
  "cover_letter": {"id": "...", "type": "cover_letter", "version": 3}
}
```

创建时网关生成 Artifact ID，版本为 1；更新时复用 ID 并将版本加 1。`Artifact.attachment` 必须与该类型最新 Assistant Message 中的 Attachment 完全一致。Artifact 内容来自客户端提交的当前 state，因此仍按不可信请求数据进行长度和类型校验。

### 7.5 Response

响应返回经过校验的完整 next state，Extension 不在本地 append 最新消息：

```json
{
  "protocol_version": 2,
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "selected_action_id": "write_cover_letter",
  "result_type": "create_artifact",
  "histories": [
    {
      "id": "assistant-message-uuid",
      "role": "assistant",
      "content": "已生成一版针对该岗位的求职信。",
      "action_id": "write_cover_letter",
      "created_at": "2026-07-19T10:24:31Z",
      "attachments": [
        {
          "id": "attachment-uuid",
          "artifact_id": "artifact-uuid",
          "version": 1,
          "type": "cover_letter",
          "title": "Cover Letter",
          "content": "Dear Hiring Manager, ..."
        }
      ]
    }
  ],
  "artifacts": {
    "cover_letter": {
      "id": "artifact-uuid",
      "type": "cover_letter",
      "version": 1,
      "title": "Cover Letter",
      "draft": "Dear Hiring Manager, ...",
      "attachment": {
        "id": "attachment-uuid",
        "artifact_id": "artifact-uuid",
        "version": 1,
        "type": "cover_letter",
        "title": "Cover Letter",
        "content": "Dear Hiring Manager, ..."
      }
    },
    "cv": null
  },
  "meta": {
    "id": "request-uuid",
    "status": "completed",
    "model": "model-id",
    "duration_ms": 1800
  }
}
```

`result_type` 反映本轮最终行为。Extension 只有在响应结构完整、`resource_url` 和当前 owner 仍匹配时，才整体替换本地 `histories` 与 `artifacts`。

为保持现有指标契约，`meta.model` 记录最终生成回复的 Specialist 模型；`meta.duration_ms` 覆盖 IntentRouter 与 Specialist 的完整编排耗时。确定性 Quick Insight Action 路径没有 Router 调用。

### 7.6 容量与一致性校验

沿用现有文本上限，并为新增嵌套结构增加确定边界：

- User Message `content`：1–10,000 字符。
- Assistant Message `content`：最多 100,000 字符。
- Artifact `draft`：最多 100,000 字符。
- Cover Letter Attachment `content`：最多 100,000 字符。
- CV Attachment `content`：最多 4,096 字符，必须是绝对 HTTP(S) URL。
- Message、Attachment 和 Artifact `title`：最多 500 字符。
- Artifact `version`：`1..2,147,483,647` 的整数。
- 每条 Assistant Message 最多一个 Attachment；User Message 必须没有 Attachment。
- `artifacts` 必须恰好包含可空的 `cv` 与 `cover_letter` 两个键。

一次 state 中 Message ID、Attachment ID、Artifact ID 分别保持唯一；`Attachment.artifact_id` 是对 Artifact ID 的正常引用。非空 Artifact 的 type 必须与 map key 一致，且它的最新 Attachment 必须与 histories 中最后一个同类型 Attachment 完全一致。请求 state 不满足这些条件时，在调用 Agent 前拒绝。

## 8. Workspace State Transition

Task Service 作为纯状态转换的编排层：

1. 校验认证状态、resource URL、消息数量、history、attachments 和 artifacts；owner 的迟到响应检查由 Extension 完成。
2. 重新采集的页面上下文与当前用户服务端简历注入 `JobChatContext`。
3. 调用 `JobMatchAgent` 获得 `ChatResult`。
4. `user_message` 先创建 User Message；Quick Insight Action 不创建 User Message。
5. 为 Assistant Message、Attachment 和新 Artifact 版本分配 UUID 与 UTC 时间。
6. 在内存中生成完整的新 histories 和 artifacts。
7. 一次性返回完整状态。

Agent 不管理消息 ID、时间戳、版本号和 Chrome 本地状态。Repository 不参与本期 Workspace 状态，因为聊天历史和 Artifact 仍由 Extension 持有。

三种状态转换精确定义为：

- `reply`：追加一条 Assistant Message；两个 Artifact 均原样返回，不增加版本。
- `create_artifact`：同类型 Artifact 必须为空；创建新 Artifact ID、`version=1` 和新 Attachment。
- `update_artifact`：同类型 Artifact 必须已存在；复用 Artifact ID、版本加 1，并创建新 Attachment。
- create/update 只检查同类型 Artifact；已有 Cover Letter 不影响创建 CV，反之亦然。
- 每轮至多创建或更新一个 Artifact，并把它附加到本轮唯一的新 Assistant Message。

输入消息限制保持不变：

- `user_message`：`len(histories) + 1 <= 10`。
- `quick_insight_action`：`len(histories) <= 10`。
- 合法请求产生的最后一条 Assistant Message 可以让本地终态达到 11 条；之后禁止继续发送或自动生成。
- Attachment 不单独计入消息数量。

## 9. Artifact 与持久化边界

### 9.1 Cover Letter

Cover Letter 不需要服务端 Artifact 持久化：

- 最新可编辑草稿保存在 `artifacts.cover_letter.draft`。
- 每次创建或更新都把完整正文写入该 Assistant Message 的 Attachment。
- 旧 Attachment 内容不修改，因此本地历史中每个 Cover Letter 版本都可继续查看和复制。

### 9.2 CV

本期 CV Attachment 继续使用固定测试预览地址：

```text
https://browser.buildwithyang.com
```

固定地址由 Gateway 写入 CV Attachment 的 `content`，Extension 只渲染响应中的 URL，不再硬编码展示地址。

最新 CV Markdown 只保存在 `artifacts.cv.draft`，用于下一轮修改。历史消息会记录 CV Artifact ID 和版本，但所有 CV Attachment 暂时可以指向同一测试地址；该地址不保证展示本轮真实生成内容，也不提供隐私隔离、历史恢复或按版本回滚。

真正的 CV 版本预览需要后续增加服务端 Artifact 持久化、用户隔离、私有对象存储和版本化访问 URL。本期明确延期，不新增数据库表、Repository 或预览 API。

## 10. Quick Insight 与 Workspace 展示

Quick Insight 页面浮层保持面向决策的卡片结构及 Actions。

Workspace 改为经典聊天模式：

```text
Compact job header + match score
Scrollable chronological messages
  User bubble
  Assistant Markdown
  Optional inline attachments
Sticky Action chips + composer
```

Workspace 中：

- 只保留匹配分数，放在页面标题/来源附近。
- 删除 Business Overview、Role Focus、Top Strength、Top Gap 和完整 Quick Insight 卡片。
- 不设置单独的 Latest Artifact 区域。
- Attachment 出现在产生它的 Assistant Message 内。
- User Message 不显示“你”或 `You`。
- Assistant Message 不显示 `Agent` 标签；左右位置和样式用于区分角色。
- 每条消息都显示时间。

时间由后端使用 UTC 返回。Extension 以浏览器本地时区显示 `HH:mm`，并在 `title` 或等价 tooltip 中展示完整本地日期与时间。Attachment 继承所属 Message 的时间，不重复显示时间戳。

## 11. Markdown

Workspace 的 `HistoryMessage.content`、`Artifact.draft` 和 Cover Letter Attachment 只返回 Markdown。Workspace 响应删除旧的 `content_html`、`html`、`sections` 和 `document`。Quick Insight 继续返回结构化 `Insight/cards`，不受 Workspace Markdown-only 契约影响。

Extension 使用随包发布的第三方 Markdown renderer 渲染 Assistant Message 和 Cover Letter Attachment。实现采用：

- Marked：Markdown 转 HTML。
- DOMPurify：清理 renderer 产生的 HTML。

Gateway 与 Extension 都不通过正则或手写 HTML 栈实现 Markdown parser，也不维护业务层 Markdown 格式白名单。Gateway 只约束结构化字段和非空/长度；Marked 支持的格式（包括 raw HTML）统一在 Extension 端渲染并由 DOMPurify 清理。依赖随 Extension 打包，不从 CDN 动态加载。

至少支持：

- 标题。
- 粗体、斜体。
- 有序和无序列表。
- 链接。
- 行内代码和代码块。
- 表格。

表格和代码块在窄 Side Panel 内部横向滚动，不能造成页面级横向溢出。User Message 仍按纯文本渲染。

## 12. 错误处理与原子性

- `IntentRouter` 必须返回合法的结构化 `RouteDecision`。首次解析失败时使用纠错提示重试一次；再次失败则返回 502，不静默路由到 GeneralQA。
- Specialist 输出必须符合 `SpecialistResult` union 和合法结果矩阵；否则返回 502。
- 任何失败都不能返回部分 history、部分 Artifact 或提前增加版本号。
- Task Service 只在 Agent 完整成功后构造经过校验的完整 next state。
- Extension 只在完整合法的 2xx 响应后整体替换 state。
- 请求失败时保留现有 histories、artifacts、选中的 Action 和输入框内容，并显示可重试错误。
- Quick Insight 自动执行失败时仍打开 Workspace，但不追加虚假的失败 Message；错误只显示在 composer 附近。
- owner 在请求期间变化时直接丢弃响应，不写入任何 Workspace。
- 迟到 401 继续使用既有 owner + token 快照规则，不能清除新登录态。
- Gateway 返回 426、任意 Task 响应 Header 版本缺失/不匹配，或成功响应的 `protocol_version` 缺失/不匹配时，Extension 显示“扩展版本不兼容，请更新扩展”和可点击的更新入口；该错误不能被当成认证失败，不能清除 token。若更新后仍出现，提示检查 Gateway 部署版本，避免无限更新循环。
- 协议错误不得覆盖 histories、artifacts、selected Action 或输入框；Quick Insight 也不得展示来自不兼容响应的部分内容。

由于本期没有服务端 Artifact 持久化，原子性边界是“一次 API 响应 + 一次 Extension state 替换”，不需要数据库事务。

## 13. 安全与隐私

- 页面正文、简历、history 和 Artifact 均按不可信输入处理，并保留现有长度限制。
- Agent 不缓存按用户区分的数据。
- Extension 继续使用 `ownerId + resourceUrl` 隔离 Workspace。
- Markdown renderer 的 HTML 必须经过 DOMPurify 后才能进入 DOM。
- CV 固定测试链接不携带用户内容，也不代表真实 CV 已经公开托管。
- 本期不把聊天历史或 Artifact 新增长期写入数据库。

## 14. 测试与验收

### 14.1 Gateway

- `current message > Action > history` 路由优先级。
- 选中 Tailor Resume 并询问建议时返回 `reply`，不增加 CV 版本。
- 明确要求生成 CV 时返回 create；已有 CV 时返回 update 且版本加 1。
- 已有 CV 后要求重写时复用同一 Artifact ID，只增加版本。
- 明确要求生成或修改 Cover Letter 时产生完整 Attachment。
- 选中 Ask More 但明确要求写 Cover Letter 时仍路由 CoverLetterAgent。
- JobAnalysisAgent 和 GeneralQAAgent 不能产生 Artifact。
- `reply` 后 CV 与 Cover Letter Artifact 均保持完全不变。
- Quick Insight Analyze 跳过 IntentRouter 并追加 Assistant reply。
- Quick Insight Tailor Resume / Cover Letter 跳过 IntentRouter 并 create/update 对应 Artifact。
- Quick Insight Tailor Resume 返回 reply、或 Cover Letter 返回错误类型时，网关返回 502 且状态不变。
- Quick Insight Ask More 不请求 Workspace API。
- User Message 请求追加 User + Assistant；Quick Insight Action 只追加 Assistant。
- Router 或 Specialist 非法输出不会改变 histories/artifacts。
- CV 与 Cover Letter 的最新 Artifact 可以并存，更新一种不影响另一种。
- 所有新 Message 有 UUID 和 UTC `created_at`。
- `user_message` 携带 9 条 history 时允许请求，成功后终态为 11 条；携带 10 条时拒绝。
- `quick_insight_action` 携带 10 条 history 时允许请求，成功后终态为 11 条；终态 11 条后禁止任何新 Agent 调用。
- Attachment 与 Quick Insight 本身均不计入消息数量。
- Workspace JSON 不包含 `html`、`sections` 或 `document`。
- 重复 ID、错误 Artifact key/type、超过一个 Attachment 或最新 Artifact/Attachment 不一致的输入在 Agent 调用前被拒绝。
- 缺失、非法或不匹配的 `X-Agent-Bridge-Protocol-Version` 在 Agent 调用前返回 426。
- Quick Insight 与 Workspace 的成功响应都返回当前 `protocol_version`。
- 所有 Task 响应都返回协议响应 Header；426 同时返回标准 `Upgrade: Agent-Bridge/2` Header。
- 旧 `POST /tasks` 固定返回 426，不调用 LLM、Agent、Resume Service 或 Repository。

### 14.2 Extension

- 后端成功响应整体替换 histories/artifacts，不本地 append。
- 失败响应保留输入框和原 state。
- owner 不匹配的迟到响应被丢弃。
- Action chips 切换不清空历史或 Artifact。
- Workspace 只显示匹配分数，不显示其余 Quick Insight cards。
- User / Assistant Message 均无发送者文字标签。
- 每条 Message 显示本地 `HH:mm`，tooltip 显示完整本地时间。
- Assistant Markdown 正确渲染标题、粗体、斜体、列表、链接、代码和表格。
- Markdown 表格与代码块不造成 Side Panel 页面级横向溢出。
- Cover Letter Attachment 在历史原位置渲染并可复制原始 Markdown。
- Cover Letter 更新后，旧 Message 中的 Attachment 正文保持不变。
- CV draft 随版本更新；不同版本 Attachment 当前允许使用同一个 Gateway 返回的测试 URL。
- 多个历史 Cover Letter Attachment 保持各自内容。
- 普通网页仍只显示 Ask More。
- 普通网页 Ask More 也走 `WorkspaceAgent.handle_chat() -> ReplyResult`，响应不包含旧 DocumentContent。
- 所有 Quick Insight / Workspace 请求都携带当前协议 Header。
- 426、响应 Header 不兼容和成功 body 版本不匹配都会显示更新入口，且不清除登录态或覆盖本地 state。
- 响应缺少 `protocol_version` 时同样拒绝应用，避免新 Extension 消费旧 Gateway 契约。

### 14.3 回归

- `POST /tasks/quick-insight` 的 Job Match Insight 和 Actions 保持可用。
- `POST /tasks` 仅保留固定 426 升级响应，不再保留旧 Agent 或 `DocumentContent` 生成链路。
- LinkedIn / Indeed resource URL 规范化和 Workspace owner 隔离保持不变。
- Extension 全部单元测试与打包测试通过。
- Gateway 全部测试和 `import app.main` 检查通过。

## 15. 未上线契约与旧入口处理

`POST /tasks/workspace -> DocumentContent` 从未发布到线上，不存在需要保护的公开兼容边界。本期直接用 `WorkspaceAgent.handle_chat() -> ChatResult` 替换该实现，并删除只服务于该未上线契约的 `DocumentDraft`、`currentDocument`、`DocumentContent` reducer 和测试。

线上旧 Extension 使用过的 `POST /tasks` 仍保留路由，但不再保留旧 Agent 生成逻辑：

- 路由固定返回 `426 Upgrade Required` 和当前协议版本、更新地址。
- 路由不解析旧 Task 文档请求，不调用 `TaskService.execute()`，也不调用任何 Agent。
- 删除旧 `TaskRequest`、`TaskResponse`、`DocumentContent`、`Section`、legacy adapter 及对应生成测试；Quick Insight 使用的 `Insight`、`Card` 与后端 Markdown renderer 不受影响。
- `modules/task/legacy/` 如果保留，仅包含最薄的 426 API shim 和说明文档，不包含 Agent、Prompt 或文档渲染实现。

这不是 legacy 行为兼容，而是明确的升级门。旧客户端必须更新后才能继续使用；新版核心代码不会因历史接口继续维护 `execute() -> DocumentContent`。

## 16. 本地状态迁移与发布

Workspace 本地 schema 增加版本号。新版本以 `artifacts` 和带 `attachments` 的 histories 替代 `currentDocument`。

当前功能尚未向公开用户发布，本期采用简单迁移：

- 保留能够通过新 schema 校验的纯文本 histories。
- 删除旧 `currentDocument`，不伪造带 Attachment 的历史消息。
- 初始化空 `artifacts`。
- 用户下一次生成 CV 或 Cover Letter 后进入新模型。

发布顺序：

1. 先把协议版本 2 的 Extension 提交 Chrome Web Store 审核，选择审核通过后手动发布，暂不推送给用户。
2. 审核通过后，部署支持协议版本 2、新 Workspace contract 和 `/tasks` 426 shim 的 Gateway。
3. 立即手动发布已审核的 Extension，并通知内部种子用户更新。
4. 发布后验证真实反向代理没有丢弃请求/响应协议 Header。

本期采用严格相等的协议门，不维护多协议兼容窗口。Gateway 切换到 Extension 自动更新完成之间，旧 Extension 只会看到原有的通用请求失败，因为旧版 UI 并不认识 426；不能依赖 426 body 主动引导旧客户端，必须人工通知内部种子用户。新版 Extension 如果连接到旧 Gateway，会因响应协议 Header/JSON 版本缺失而显示版本不兼容提示，并且不会清理登录态或用旧响应覆盖本地 Workspace。

## 17. 后续演进

后续独立设计与实现：

- CV Artifact 服务端持久化和不可变版本预览。
- 认证后的私有 CV 下载/预览 URL。
- 服务端 Chat Thread 与跨设备同步。
- File / Image Attachments。
- MockInterviewAgent、SalaryAgent、CompanyResearchAgent。
