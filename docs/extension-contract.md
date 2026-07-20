# Extension ↔ Gateway Contract

本文是 Extension 与 Gateway 当前 wire contract 的工程事实来源。协议整数独立于
`manifest.json` 发布版本，当前版本为：

```text
X-Agent-Bridge-Protocol-Version: 3
```

## 1. 公开接口

```text
POST /tasks/quick-insight -> ordinary JSON QuickInsightResponse
POST /tasks/workspace     -> application/x-ndjson Workspace event stream
```

- Quick Insight 是只读页面洞察，不创建 Message 或 Artifact。
- Workspace 是共享历史的无状态 transition；reply 支持 Markdown delta，Artifact 原子完成。
- `POST /tasks` 只返回升级提示，不再执行 Agent。
- 公开请求不接受 `agent`；Gateway 根据 Page Context 选择无状态能力，并规范化
  `resourceUrl`。

## 2. Protocol gate

两个接口的每个 POST 都发送：

```http
X-Agent-Bridge-Protocol-Version: 3
```

Gateway 在 Session、鉴权、request body 解析和路由之前校验原始 Header。缺失、重复、非法
或旧版本都返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/3
X-Agent-Bridge-Protocol-Version: 3
Content-Type: application/json

{
  "code": "extension_update_required",
  "message": "Extension update required",
  "required_protocol_version": 3,
  "update_url": "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
}
```

通过 gate 的 Task 响应，包括错误响应，都带当前 protocol Header。Quick Insight JSON body
与 Workspace `completed.response` 必须带 `protocol_version: 3`。Extension 在认证和业务
错误之前校验 Header；不兼容时显示扩展更新入口，不清 token 或 local Workspace。

`OPTIONS` 与非 POST 不经过版本 gate。CORS 必须允许并暴露 protocol Header。

## 3. Page Context

[content.js](../extension/content.js) 只采集纯文本：

```js
{ url, title, selectedText, pageText, imageText }
```

| 字段 | 来源 | Extension 边界 |
| --- | --- | --- |
| `url` | `location.href` | 当前完整 URL |
| `title` | `document.title` | 当前标签页标题 |
| `selectedText` | 当前选区 | 用户明确关注的文字 |
| `pageText` | `document.body.innerText` | 压缩空白后最多 20,000 字符 |
| `imageText` | `alt` / `title` / `figcaption` / `aria-label` | 去重最多 40 条、合计最多 4,000 字符 |

不采集图片像素、HTML、CSS 或脚本。每次 Workspace 请求前重新采集，且不写入 local
Workspace。

## 4. Quick Insight JSON

Request：

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

Response：

```text
QuickInsightResponse
├── request: QuickInsightRequest
├── insight: Insight
├── actions: Action[]
├── workspace: {resource_url, default_action_id}
├── meta: ExecutionMeta
└── protocol_version: 3
```

稳定 Action ids：`analyze`、`tailor_resume`、`write_cover_letter`、`ask_more`。
Job Match 使用 score/details/text typed cards；普通页面摘要是 Gateway 净化后的
`body_html` text card。

点击前三个 Action 会 seed Workspace 并发送 `trigger=quick_insight_action`；`ask_more`
只打开并聚焦输入框。确定性 Quick commands 使用固定 `ChatPlan`，不伪造 User Message。

## 5. Workspace Request

Workspace 额外发送：

```http
Accept: application/x-ndjson
Content-Type: application/json
```

User Message：

```json
{
  "trigger": "user_message",
  "operationId": "00000000-0000-0000-0000-000000000001",
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

Quick Insight Action 使用同样字段，但 `trigger=quick_insight_action` 且禁止 `message`。
每个请求都要求 Extension 生成的 UUID `operationId`。`resourceUrl` 不是授权依据；Gateway
从当前 `url` 重新规范化并要求两者相等。

`user_message` 最多带 9 条 histories，message 为 1–10,000 字符；Quick Action 最多带
10 条 histories。Action 是用户消息的强意图提示，当前用户明确请求优先；`ChatPlanner`
选择一个 Specialist 和 reply/artifact 输出模式。

## 6. Workspace NDJSON

Gateway 成功启动 stream 后返回：

```http
Content-Type: application/x-ndjson
Cache-Control: no-cache
X-Accel-Buffering: no
```

每行是一个 UTF-8 JSON event。Extension 要求 first event 为 sequence 0 `started`，同一
`operation_id` 的 sequence 严格递增，并且 stream 恰好以 `completed` 或 `failed` 终止：

```text
started   {operation_id, sequence, created_at}
status    {operation_id, sequence, stage, artifact_type?}
delta     {operation_id, sequence, text}
completed {operation_id, sequence, response}
failed    {operation_id, sequence, code, message, recoverable}
```

`stage` 为 `routing | generating_reply | generating_artifact | finalizing`。
`artifact_type` 只在 `generating_artifact` 存在，值为 `cv | cover_letter`。其他 status 不
输出该字段。

### 6.1 Reply

普通 reply 使用 Chat Completions streaming。模型 raw Markdown chunk 变成 `delta`，
Extension 累积后增量渲染；完整 Markdown 仍在 terminal response 的 Assistant Message 中。

### 6.2 Artifact

CV / Cover Letter 生成时只发送 status，不发送 draft delta。Specialist chunk 在 Agent 内部
累积，完成校验后才形成 typed result。完整 Artifact draft 和 Attachment 只出现在
`completed.response`；失败、断开或取消都不能暴露 partial draft。

所有模型生成调用都使用 OpenAI-compatible Chat Completions，不使用 Responses API。
Specialist 返回 raw Markdown，不返回 JSON transport envelope。

### 6.3 Terminal response

```text
WorkspaceResponse
├── resource_url
├── selected_action_id
├── result_type: reply | create_artifact | update_artifact
├── histories: HistoryMessage[]
├── artifacts: {cv: Artifact|null, cover_letter: Artifact|null}
├── meta: ExecutionMeta
└── protocol_version: 3
```

`completed.response` 是唯一 canonical next state。`started`、`status`、`delta` 全部 transient；
Extension 不能从它们 append canonical Message 或修改 Artifact。

## 7. Message、Attachment 与 Artifact

`HistoryMessage`：

```json
{
  "id": "00000000-0000-0000-0000-000000000010",
  "role": "assistant",
  "content": "已生成一版求职信。",
  "action_id": "write_cover_letter",
  "created_at": "2026-07-20T10:00:00Z",
  "attachments": []
}
```

- id 为 UUID，`created_at` 为 UTC；合法 response 最多 11 条 histories。
- User Message 不能带 Attachment；每条 Assistant Message 最多一个 Attachment。
- Assistant content、Artifact draft 和 Cover Letter Attachment 最多 100,000 字符。

`artifacts` 恰好有 nullable `cv` / `cover_letter` 两个 key。创建 version=1；更新复用同
类型 Artifact id 并递增 version。`Artifact.attachment` 必须等于 histories 中最后一个同
类型 Attachment。CV Attachment content 是绝对 HTTP(S) URL；Cover Letter content 是该
历史版本的完整 Markdown。

Gateway 与 Extension 都校验 UUID 唯一性、引用、类型、版本和最新 Attachment 一致性。
任一检查失败都保留旧 canonical state。当前 CV URL 仍是临时测试预览，并不代表按用户
隔离或版本化托管。

## 8. 渲染边界

Workspace Markdown 字段是 `HistoryMessage.content`、`Artifact.draft` 与 Cover Letter
`Attachment.content`。Gateway 不生成 Workspace HTML。

[markdown.js](../extension/markdown.js) 使用包内 Marked（GFM）生成 HTML，再用 DOMPurify
净化。Assistant reply 与 Cover Letter 支持标题、强调、列表、链接、代码和表格；User
Message 使用 `textContent`。运行时不从 CDN 加载模块。

## 9. Local state、optimistic UI 与失败恢复

canonical state 使用 storage key：

```text
agent-bridge:workspace:v2:<encoded owner>:<encoded resourceUrl>
```

主体保存在 `chrome.storage.local`；tab 到 owner/resource 的 active mapping 保存在
`chrome.storage.session`。不同 owner/resource 隔离，本期没有服务端 Thread、Artifact
Repository 或跨设备恢复。

- 同一 owner/resource 使用 keyed queue；每次在队列内重读最新 state 并重新采集页面。
- 发送时 Side Panel 先显示 optimistic User Message 和 transient Assistant，但不持久化。
- delta 快照以最多 50ms 的频率绘制；completed 先完成 canonical storage commit，再发布。
- 只有 `completed.response` 调用 `applyWorkspaceResponse()` 并写 local state。
- failed、断流、超时、取消、schema/protocol/storage 错误不增加 history、不更新 Artifact，
  并恢复原始 composer 输入供重试。
- owner、tab、resource 或 operation 已变化时，迟到事件被丢弃；迟到 401 只有 owner/token
  仍匹配才清认证。

## 10. Nginx streaming boundary

云端 exact route 必须关闭代理缓冲和缓存：

```nginx
location = /api/tasks/workspace {
    proxy_pass http://gateway:17321/tasks/workspace;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    # preserve Host / X-Real-IP / X-Forwarded-For / X-Forwarded-Proto
}
```

通用 `/api/` location 保持原有前缀 rewrite。Gateway 与 Nginx 任一层重新缓冲都可能让
reply delta 延迟到终态。

## 11. Extension 协同发布边界

通常可以只改 Gateway：Prompt、模型、文案、内部页面能力选择、URL 规范化细节，以及
现有 wire shape 内的 ChatPlanner / Specialist 编排。

以下变更必须同步修改 Extension，并在不兼容时提升 protocol 版本：顶层或事件字段、事件
顺序与终态、Action id、Insight card type、Attachment / Artifact type、渲染原语、Quick
Action 语义、本地 schema 或迁移规则。

原则：内容和后端编排可以独立演进；wire shape、稳定 id、渲染原语与 local state 必须
协同发布。
