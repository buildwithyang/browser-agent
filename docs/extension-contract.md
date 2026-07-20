# Extension ↔ Gateway Contract

本文是 Extension 与 Gateway 当前 wire contract 的工程事实来源。它用于判断一次改动是纯
后端实现，还是需要提升协议版本、修改扩展并重新发布 Chrome Web Store 包。

当前协议版本：

```text
X-Agent-Bridge-Protocol-Version: 2
```

协议整数独立于 `manifest.json` 的发布版本。完整产品与编排语义见
[Job Match Workspace Orchestration Design](superpowers/specs/2026-07-19-job-match-workspace-orchestration-design.md)。

## 1. 两个公开场景接口

```text
POST /tasks/quick-insight
  -> QuickInsightResponse

POST /tasks/workspace
  -> WorkspaceResponse
```

- Quick Insight 是 decision-first 的只读页面浮层，使用 typed cards。
- Workspace 是共享历史的无状态 state transition，使用 Markdown Message 与 Artifact。
- `POST /tasks` 只保留升级 shim，始终返回 `426`，不再执行旧 Agent。
- `POST /tasks/current-task` 从未上线，当前代码不存在该接口。

公开请求不接受 `agent`。Gateway 根据当前 Page Context 做 Context Routing，并用规范化
`resourceUrl` 标识 Workspace 业务资源。

## 2. 协议版本门

Extension 对两个新版接口的每个请求都发送：

```http
X-Agent-Bridge-Protocol-Version: 2
```

Gateway 在 Session、鉴权、request body 解析和路由之前严格校验该 Header。缺失、重复、
无法解析或不等于 `2` 时返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/2
X-Agent-Bridge-Protocol-Version: 2
Content-Type: application/json

{
  "code": "extension_update_required",
  "message": "Extension update required",
  "required_protocol_version": 2,
  "update_url": "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
}
```

通过协议 gate 的所有 Task 响应，包括 2xx、400、401、429、502，都必须携带当前协议
Header。成功的 Quick Insight / Workspace body 还必须有 `protocol_version: 2`。

Extension 在认证和业务错误之前先检查响应 Header；成功时再检查 body 版本。任一版本
缺失或不相等都会变成 `ExtensionUpdateRequiredError`，不会清除 token，也不会把响应
写入本地 Workspace。

`OPTIONS` 与非 POST 请求不经过版本 gate。CORS 必须允许请求并暴露协议 Header。

## 3. Page Context

[content.js](../extension/content.js) 只采集纯文本：

```js
{
  url,
  title,
  selectedText,
  pageText,
  imageText,
}
```

| 字段 | 来源 | Extension 边界 |
| --- | --- | --- |
| `url` | `location.href` | 当前完整 URL |
| `title` | `document.title` | 当前标签页标题 |
| `selectedText` | 当前选区 | 用户明确关注的文字 |
| `pageText` | `document.body.innerText` | 压缩空白后最多 20,000 字符 |
| `imageText` | `alt` / `title` / `figcaption` / `aria-label` | 去重最多 40 条、合计最多 4,000 字符 |

不采集或发送图片像素、页面 HTML、CSS、脚本。Page Context 每次 Workspace 请求前重新
采集，不长期写入本地 Workspace。

## 4. Quick Insight

### 4.1 Request

```json
{
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "selected JD",
  "pageText": "visible page text",
  "imageText": "image text clues",
  "lang": "zh"
}
```

`lang` 为 `auto | zh | en`。Request 不包含 owner、Workspace state 或 Agent selector；Bearer
token 在 HTTP Header 中发送。

### 4.2 Response

```text
QuickInsightResponse
├── request: QuickInsightRequest
├── insight: Insight
├── actions: Action[]
├── workspace: WorkspaceDescriptor
├── meta: ExecutionMeta
└── protocol_version: 2
```

`WorkspaceDescriptor`：

```json
{
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "default_action_id": "analyze"
}
```

`Action` 只有：

```json
{"id": "tailor_resume", "title": "Tailor Resume"}
```

当前 Extension 与 Gateway 共同接受的稳定 Action ids：

- `analyze`
- `tailor_resume`
- `write_cover_letter`
- `ask_more`

### 4.3 Insight cards

```text
Insight
├── title
└── cards[]
    ├── score   {id, title, score, max_score, recommendation, reason}
    ├── text    {id, title, body_html}
    └── details {id, title, items, summary}
```

Job Match 使用结构化 score / details / text cards。普通页面摘要由 Gateway 用 Markdown
renderer 生成经过净化的 `body_html`，再放进 text card。Workspace 不消费这个 HTML。

### 4.4 Action 点击语义

- `analyze`、`tailor_resume`、`write_cover_letter`：先打开并 seed Workspace，再发送
  `trigger=quick_insight_action`。
- `ask_more`：只打开 Workspace 并聚焦输入框，不请求 `/tasks/workspace`。

前三个 Action 是确定性 Quick commands；Gateway 跳过 IntentRouter，且不伪造 User
Message。它们仍携带该资源已有的完整 histories 与 artifacts。

## 5. Workspace Request

`POST /tasks/workspace` 使用 `trigger` 作为 discriminator。

### 5.1 User Message

```json
{
  "trigger": "user_message",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "selected JD",
  "pageText": "visible page text",
  "imageText": "image text clues",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "actionId": "tailor_resume",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null},
  "message": "我的哪段经历最值得突出？"
}
```

`message` 必须为 1–10,000 字符，且已有 histories 最多 9 条。

### 5.2 Quick Insight Action

```json
{
  "trigger": "quick_insight_action",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "selected JD",
  "pageText": "visible page text",
  "imageText": "image text clues",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "actionId": "tailor_resume",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null}
}
```

该 variant 禁止 `message`，已有 histories 最多 10 条。`resourceUrl` 不是授权依据；Gateway
会从当前 `url` 重新规范化并要求两者相等。

Workspace Action 是强意图提示，而不是强制 Artifact 命令。用户消息优先于 Action，
Gateway Orchestrator 决定普通回复还是正式产物。

## 6. Workspace Response

Extension 对顶层对象做 exact-key 校验：

```text
WorkspaceResponse
├── resource_url
├── selected_action_id
├── result_type: reply | create_artifact | update_artifact
├── histories: HistoryMessage[]
├── artifacts: {cv: Artifact|null, cover_letter: Artifact|null}
├── meta: ExecutionMeta
└── protocol_version: 2
```

成功响应是完整 next state。Extension 不能自行 append User / Assistant Message，而是在
完整校验后整体替换 histories 与 artifacts。

### 6.1 HistoryMessage

```json
{
  "id": "message-uuid",
  "role": "assistant",
  "content": "已生成一版求职信。",
  "action_id": "write_cover_letter",
  "created_at": "2026-07-20T10:00:00Z",
  "attachments": []
}
```

- id 为 UUID，`created_at` 必须是 UTC。
- User content 为 1–10,000 字符；Assistant content 最多 100,000 字符。
- `action_id` 可为 null 或稳定 Action id。
- 每条 Message 最多一个 Attachment；User Message 必须没有 Attachment。
- 合法响应 histories 最多 11 条。

### 6.2 Attachment

```json
{
  "id": "attachment-uuid",
  "artifact_id": "artifact-uuid",
  "version": 1,
  "type": "cover_letter",
  "title": "Cover Letter",
  "content": "Dear Hiring Manager, ..."
}
```

- `cover_letter.content` 是该历史版本的完整 Markdown 快照。
- `cv.content` 必须是最多 4,096 字符的绝对 HTTP(S) URL。
- Attachment 是所属 Assistant Message 的不可变快照；更新会追加新 Message，不改旧值。
- File / Image 尚不是协议版本 2 的合法类型。

### 6.3 Artifact

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

`artifacts` 必须恰好有 `cv`、`cover_letter` 两个 nullable key。创建时 version=1；更新同
类型时复用 Artifact id 并递增 version。`Artifact.attachment` 必须与 histories 中最后一个
同类型 Attachment 完全相等。

Gateway 与 Extension 都校验 UUID 唯一性、Artifact 引用、固定 key/type、版本与最新
Attachment 一致性。任一检查失败都保留旧 state。

当前 CV Attachment URL 由 Gateway 固定返回 `https://browser.buildwithyang.com`。CV
draft 可用于下一轮修改，但测试 URL 不是真实、私有或版本化的生成结果。

## 7. Markdown 与渲染边界

Workspace 只传 Markdown：

- `HistoryMessage.content`
- `Artifact.draft`
- Cover Letter `Attachment.content`

Workspace 响应没有 `content_html`、`html`、`sections`、`document` 或
`currentDocument`。Gateway 不解析 Workspace Markdown。

[markdown.js](../extension/markdown.js) 使用随包发布的 Marked（GFM）生成 HTML，再用
DOMPurify 净化。依赖不从 CDN 加载。Assistant Message 与 Cover Letter Attachment 可渲染
标题、强调、列表、链接、代码和表格；User Message 使用 `textContent`。

CV Attachment 只渲染 Gateway 响应中的 URL。Cover Letter 的复制按钮复制原始 Markdown，
不是渲染后的 HTML。

## 8. 本地 state 与迁移

Workspace schema 版本为 2，存储键为：

```text
agent-bridge:workspace:v2:<encoded owner>:<encoded resourceUrl>
```

state 字段：

```text
schemaVersion
resourceUrl
pageTitle
quickInsight
actions
selectedActionId
histories
artifacts
updatedAt
```

Extension 同时在 `chrome.storage.session` 保存 tab 到 owner/resource key 的 active mapping；
历史主体在 `chrome.storage.local`。owner 变化时清除 tab mapping，不删除其他 owner 隔离的
local records。

加载仍指向 v1 key 的 active Workspace 时：

1. 只迁移能通过 v2 校验且没有 Attachment 的旧 Message。
2. 删除旧 `currentDocument` 语义，初始化空 artifacts。
3. 先写入并重新读取 v2 state，校验后切换 active mapping。
4. 最后删除旧 v1 record；失败时尽力恢复旧 mapping。

本期没有服务端 Thread、Artifact Repository 或跨设备恢复。Gateway 仍可把一次调用写入
既有 task record，但该记录不是可恢复 Workspace state。

## 9. 原子应用与并发边界

- 同一 owner/resource 的 Workspace operations 用 keyed queue 串行。
- 每个 operation 在队列内重新加载 canonical local state，再采集当前 Page Context。
- 请求捕获 owner/token snapshot；owner 不匹配的迟到结果会被丢弃。
- 迟到 401 只有 owner 与 token 都仍匹配时才清理认证。
- 只有完整合法的 2xx response 才一次性写入 local state。
- 网络、Agent、schema、protocol 或 storage 失败都不产生 optimistic / partial Message。

Side Panel 会保留失败时的 composer draft，并在输入区附近显示可重试错误。

## 10. 哪些改动需要重新发布 Extension

通常可以只改 Gateway：

- 修改现有 Agent Prompt、模型或输出文案。
- 调整 Gateway 内部 Context Routing 与 URL 规范化规则，同时保持既有资源语义。
- 在现有 card / Action / Message / Artifact contract 内改变具体内容。
- 改变 Orchestrator 如何在四个现有 Specialist 之间路由。

必须修改 Extension、提升协议版本（若 wire 不兼容）并重新发布：

- 新增或删除 Workspace 顶层字段，或改变任一字段类型 / 必填性。
- 新增 Attachment / Artifact 类型（如 file、image）。
- 新增稳定 Action id；Extension 当前有固定 Action id 校验与 Quick command 映射。
- 新增 Insight card type 或新渲染原语。
- 改变 Quick Action 的 open-only / deterministic request 语义。
- 增加新的响应 HTML、交互控件、文件下载或图片展示能力。
- 修改本地 Workspace schema 或迁移规则。

原则：**内容和后端编排可以独立演进；wire shape、稳定 id、渲染原语和本地 state 必须与
Extension 协同发布。**
