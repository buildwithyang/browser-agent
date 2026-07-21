# Extension ↔ Gateway Contract

本文是 Extension 与 Gateway 当前 wire contract 的工程事实来源。协议整数独立于
`manifest.json` 发布版本，当前版本为：

```text
X-Agent-Bridge-Protocol-Version: 4
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
X-Agent-Bridge-Protocol-Version: 4
```

Gateway 在 Session、鉴权、request body 解析和路由之前校验原始 Header。缺失、重复、非法
或旧版本都返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/4
X-Agent-Bridge-Protocol-Version: 4
Content-Type: application/json

{
  "code": "extension_update_required",
  "message": "Extension update required",
  "required_protocol_version": 4,
  "update_url": "https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai"
}
```

通过 gate 的 Task 响应，包括错误响应，都带当前 protocol Header。Quick Insight JSON body
与 Workspace `completed.response` 必须带 `protocol_version: 4`。Extension 在认证和业务
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
├── shortcuts: PromptShortcut[]
├── workspace: {resource_url}
├── meta: ExecutionMeta
└── protocol_version: 4
```

稳定 Prompt Shortcut ids：`analyze`、`tailor_resume`、`write_cover_letter`、`ask_more`。
Job Match 使用 score/details/text typed cards；普通页面摘要是 Gateway 净化后的
`body_html` text card。

每个 Shortcut 都有严格的 `{id,title,prompt}` 字段并按 `lang` 本地化；岗位页面返回四个，
普通页面只返回 Prompt 为空的 `ask_more`。点击只 seed/open Workspace、替换 composer 并
聚焦，不自动发送，也不把 Shortcut id 带入后续 Workspace 请求。

## 5. Workspace Request

Workspace 额外发送：

```http
Accept: application/x-ndjson
Content-Type: application/json
```

User Message：

```json
{
  "operationId": "00000000-0000-0000-0000-000000000001",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "selected JD",
  "pageText": "visible page text",
  "imageText": "image text clues",
  "intent": "JOB PAGE INTENT",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null},
  "message": "我的哪段经历最值得突出？"
}
```

每个请求都要求非空 `message` 和 Extension 生成的 UUID `operationId`。`resourceUrl` 不是授权依据；Gateway
从当前 `url` 重新规范化并要求两者相等。

message 为 1–10,000 字符。第 10 个 canonical User Message 允许发送，第 11 个拒绝。
`ChatPlanner` 对每条消息按 `current message > current Artifacts > histories` 选择一个
Specialist 和 reply/artifact 输出模式；客户端没有隐藏路由参数。

Analyze reply 的 Markdown comparison table 必须且只能使用 `JD 要求 | 匹配情况` 两列，
英文使用 `JD Requirement | Match`。Tailor Resume Shortcut 先返回修改计划，确认后才生成
CV；Cover Letter 生成/更新纯文本、可复制的 Artifact。

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
Specialist 返回 raw text，不返回 JSON transport envelope；reply 与 CV 使用 Markdown，
Cover Letter 使用纯文本。

### 6.3 Terminal response

```text
WorkspaceResponse
├── resource_url
├── result_type: reply | create_artifact | update_artifact
├── histories: HistoryMessage[]
├── artifacts: {cv: Artifact|null, cover_letter: Artifact|null}
├── meta: ExecutionMeta
└── protocol_version: 4
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
  "created_at": "2026-07-20T10:00:00Z",
  "attachments": []
}
```

- id 为 UUID，`created_at` 为 UTC；pure-v4 histories 只包含完整、按顺序排列的
  User/Assistant pair，response 最多 10 个 pair / 20 条 histories。
- 旧本地 Workspace schema 会被丢弃并创建全新的 schema-v3 Workspace；旧 histories 和
  Artifacts 不转换。
- User Message 不能带 Attachment；每条 Assistant Message 最多一个 Attachment。
- Assistant content、Artifact draft 和 Cover Letter Attachment 最多 100,000 字符。

`artifacts` 恰好有 nullable `cv` / `cover_letter` 两个 key。创建 version=1；更新复用同
类型 Artifact id 并递增 version。`Artifact.attachment` 必须等于 histories 中最后一个同
类型 Attachment。CV Attachment content 是绝对 HTTP(S) URL；Cover Letter content 是该
历史版本的完整纯文本。

Gateway 与 Extension 都校验 UUID 唯一性、引用、类型、版本和最新 Attachment 一致性。
任一检查失败都保留旧 canonical state。当前 CV URL 仍是临时测试预览，并不代表按用户
隔离或版本化托管。

## 8. 渲染边界

Assistant reply 与 CV `Artifact.draft` 使用 Markdown；Cover Letter draft/Attachment 和
User Message 使用纯文本。Gateway 不生成 Workspace HTML。

[markdown.js](../extension/markdown.js) 使用包内 Marked（GFM）生成 HTML，再用 DOMPurify
净化 Assistant reply。Cover Letter 与 User Message 使用纯文本渲染；Cover Letter 保持
可直接复制。运行时不从 CDN 加载模块。

## 9. Local state、optimistic UI 与失败恢复

canonical state 使用 storage key：

```text
agent-bridge:workspace:v3:<encoded owner>:<encoded resourceUrl>
```

主体保存在 `chrome.storage.local`；tab 到 owner/resource 的 active mapping 保存在
`chrome.storage.session`。不同 owner/resource 隔离，本期没有服务端 Thread、Artifact
Repository 或跨设备恢复。

local schema v3 保存 Quick Insight、Shortcuts、histories 与 Artifacts，不保存 Shortcut
selection。旧 local schema 不转换：精确旧 record 或指向非 v3 record 的 mapping 会被
丢弃，再创建新的空 v3 Workspace；不保留旧 histories / Artifacts，也不扫描其他
owner/resource。

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
顺序与终态、Prompt Shortcut shape/id、Insight card type、Attachment / Artifact type、
渲染原语、本地 schema 或旧状态处理规则。

原则：内容和后端编排可以独立演进；wire shape、稳定 id、渲染原语与 local state 必须
协同发布。
