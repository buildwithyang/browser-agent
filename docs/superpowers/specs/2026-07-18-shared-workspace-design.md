# Browser Agent Shared Workspace Design

日期：2026-07-18

实现状态：本仓库已实现 Quick Insight + Shared Workspace 的网关与扩展代码。本设计不代表云端网关或 Chrome 应用商店版本已经发布；上线仍需分别部署网关并发布扩展。`POST /tasks/current-task` 从未在线上发布，已从代码删除。

## 1. 目标

Browser Agent 对同一个网页只提供一个 Workspace。Quick Insight 负责快速判断，Action 负责选择下一条消息的处理能力，所有 Action 共享同一份聊天历史。

```text
Right Click → Quick Insight → Action → Workspace → Follow-up
```

本期不实现服务端会话、跨设备恢复、页面内容版本检测或“页面内容已更新”提示。

## 2. Workspace 身份

后端 Context Router 使用规范化后的 `resourceUrl` 作为页面业务资源标识，并在 Quick Insight 响应中返回 Workspace 描述。扩展以它生成本地存储键：

```text
workspaceKey = authenticatedUserId + ":" + resourceUrl
```

扩展 token 签发响应同时返回稳定的 `user_id`，网页连接扩展时一并传入并保存为 Workspace owner。匿名自部署使用固定的 `anonymous` 标识。Workspace 身份不使用页面正文哈希，避免动态内容导致同一页面产生多个 Workspace。

规范化规则：

- LinkedIn：优先读取 `/jobs/view/{job_id}`，其次读取 `currentJobId`，统一生成 `https://www.linkedin.com/jobs/view/{job_id}`。
- Indeed：读取 `jk` 或 `vjk`，保留地区 host，统一生成 `https://{host}/viewjob?jk={job_id}`。
- 普通网页：移除 fragment、`utm_*` 等追踪参数；保留会改变业务资源的其他参数。

无法解析专用岗位 ID 时，安全回退普通网页 URL 规范化规则。

## 3. Workspace 状态

Workspace 存在 `chrome.storage.local`，不写入网关数据库：

```text
WorkspaceState
├── resourceUrl
├── pageTitle
├── quickInsight
├── actions[]
├── selectedActionId
├── histories[]
└── currentDocument
```

`quickInsight` 是只读的首屏上下文，`actions` 保存后端最近一次声明的能力。`histories` 按时间保存用户消息和 Agent 回复。`currentDocument` 保存最新产物，供 Cover Letter、Resume 等连续修改。

Follow-up 请求最多携带 10 条输入消息：

- 用户发送和 Agent 回复各算一条。
- 发送前必须保证历史消息加当前用户消息不超过 10 条。
- 后端再次校验，不能只依赖扩展。
- `len(histories) + 1` 不得超过 10，其中 `1` 是当前用户消息。
- Agent 为最后一次合法请求生成的回复仍写入完整本地历史，因此终态记录可能包含 11 条消息；此后禁止继续发送。
- 达到上限后保留完整历史和最新产物；本期不截断、不总结历史。

## 4. Actions

Action 由 Quick Insight 响应返回，扩展不按网站写死 Action。选中 Action 只影响下一次请求的任务能力，不创建新 Workspace，也不清空历史。

LinkedIn / Indeed：

- `analyze`，默认选中。
- `tailor_resume`。
- `write_cover_letter`，界面标题为 `Generate Cover Letter`。
- `ask_more`。

普通网页：

- `ask_more`，默认选中。

Action 直接平铺在 Workspace 输入框附近。发送请求时，扩展提交当前 `actionId`，后端 Agent 根据 Action 选择执行策略。

## 5. 请求契约

`POST /tasks/quick-insight` 保持只返回 Insight 和 Actions，并增加 Workspace 描述：

```json
{
  "workspace": {
    "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
    "default_action_id": "analyze"
  }
}
```

唯一的 Workspace 接口 `POST /tasks/workspace` 接收完整的 Follow-up 上下文：

```json
{
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前页面重新采集的 JD 内容",
  "actionId": "tailor_resume",
  "histories": [
    {"role": "user", "content": "这个岗位最看重什么？"},
    {"role": "assistant", "content": "核心是 Agent 和 MCP 经验。"}
  ],
  "currentDocument": {
    "kind": "resume",
    "title": "Tailored Resume",
    "text": "当前最新产物的完整 Markdown"
  },
  "message": "根据刚才的分析突出我的 Go 项目。"
}
```

新接口不接受公开的 Agent 选择器：后端根据页面上下文完成 Context Routing，`AgentName` 只作为网关内部枚举。`resourceUrl` 只用于关联客户端 Workspace，不作为授权依据；后端根据 `url` 再次规范化并校验它。Side Panel 每次发送前从当前标签页重新采集 Page Context，不把整页正文长期保存在 Workspace。后端保持 Agent 无状态，每次使用请求携带的页面上下文、共享历史、最新文档和当前用户的服务端简历完成生成。

`currentDocument` 是有界的编辑输入，只回传 `kind`、`title`、`text`；HTML 和 sections 由网关重新生成。用户输入和用户历史单条最多 10,000 字符；Assistant 历史与文档正文最多 100,000 字符。

响应返回完整的新历史，而不是要求扩展自行 append：

```json
{
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "selected_action_id": "tailor_resume",
  "histories": [
    {"role": "user", "content": "这个岗位最看重什么？"},
    {"role": "assistant", "content": "核心是 Agent 和 MCP 经验。"},
    {"role": "user", "content": "根据刚才的分析突出我的 Go 项目。"},
    {"role": "assistant", "content": "已强化 Go 项目以及 Agent 相关经验。"}
  ],
  "document": {
    "kind": "resume",
    "title": "Tailored Resume",
    "text": "完整 Markdown",
    "html": "<article>...</article>",
    "sections": []
  }
}
```

扩展用响应中的 `histories` 和 `document` 整体替换本地 Workspace 状态。后端不持久化这些内容，只执行一次确定的状态转换。

`POST /tasks/current-task` 从未部署到线上，也没有已发布扩展依赖，因此直接删除，不保留 deprecated alias。已经在线的旧 `POST /tasks` 继续由 `modules/task/legacy/` 隔离兼容。

## 6. 组件边界

- `content.js`：采集原始页面 URL 和页面内容。
- `background.js`：使用后端返回的 Workspace 描述加载或保存 Workspace、请求当前标签页 Page Context、发起网关请求、打开 Side Panel。
- Side Panel：渲染共享消息历史、平铺 Actions、管理输入与发送状态。
- Gateway Context Router：路由 Agent，并规范化页面业务资源 URL。
- `TaskService`：解析 Agent、校验消息限制、注入当前用户简历并调用 Agent。
- `TaskAgent`：根据 Action、历史和当前消息生成下一条回复及最新文档，不缓存用户状态。

Side Panel 不直接决定 LinkedIn / Indeed 能力集合；它只渲染后端返回的 Actions。

## 7. 数据流

```text
Quick Insight response with Workspace descriptor
  → load WorkspaceState
  → user selects Action
  → collect current tab Page Context
  → capture current owner/token snapshot
  → POST /tasks/workspace with histories + current message + currentDocument
  → verify response still belongs to the current owner
  → replace histories and currentDocument with the complete response
  → persist WorkspaceState under owner + resource key
```

Quick Insight 的结果不是聊天消息，不计入 10 条限制。第一次进入 Workspace 时可以展示 Quick Insight 摘要作为只读上下文，但不重复写入聊天历史。

## 8. 错误处理

- Workspace 读取失败：创建空 Workspace，不影响 Quick Insight。
- Workspace 写入失败：保留当前已渲染状态并提示本地保存失败。
- 网关请求失败：不修改历史或文档，输入框保留当前用户输入以便重试。
- Action 已被后端移除：本次发送失败；用户重新运行 Quick Insight 后，扩展使用最新 Actions 并回退默认 Action。
- 历史超过 10 条：扩展和网关都拒绝请求，现有历史不变。

### 8.1 身份切换时的最小并发边界

每次请求开始时捕获 `{ownerId, token}` 快照：

- 正常响应返回时只检查 owner。如果当前 `user_id` 与请求开始时不同，直接丢弃响应，不写入任何 Workspace，并让 Side Panel 重置。
- 401 响应只有在当前 owner **和** token 都仍与请求快照一致时才清理登录态；旧 token 的迟到 401 不得清理新登录态。
- owner 变化时清除 tab 级 session 映射，但保留按 owner 隔离的本地 Workspace，使原用户重新登录后仍可恢复自己的历史。
- 同一 `user_id` 下的 OPEN/SEND 顺序竞态，以及 A → B → A 的 ABA 身份切换不在本期并发保证范围；不为这两个边界增加 epoch、事务或统一队列。

## 9. 测试与验收

- 不同 LinkedIn 搜索 URL 中相同 `currentJobId` 得到相同 `resourceUrl`。
- LinkedIn `/jobs/view/{id}` 与 `currentJobId={id}` 进入同一 Workspace。
- Indeed `jk` 与 `vjk` 相同值进入同一 Workspace。
- 普通网页 fragment 和追踪参数变化不创建新 Workspace。
- Action 切换不清空消息或最新产物。
- LinkedIn / Indeed 默认 `analyze`，普通网页默认 `ask_more`。
- Side Panel Actions 平铺在输入框附近。
- `len(histories) + 1 == 10` 时允许提交；该次 Agent 回复写入后禁止继续发送。
- `len(histories) + 1 > 10` 时前后端都拒绝。
- 扩展重新加载后，同一浏览器中的 Workspace 可以从 `chrome.storage.local` 恢复。
- 不同用户和不同 `resourceUrl` 的历史不会互相读取。
- 请求期间切换到不同 `user_id` 时，迟到响应被丢弃，Side Panel 重置。
- 迟到 401 只有在 owner + token 快照仍匹配时才清理当前登录态。

## 10. 发布边界

- 当前新代码使用 `POST /tasks/quick-insight` 和 `POST /tasks/workspace`。
- `POST /tasks/current-task` 从未部署，已直接删除且不保留兼容 alias。
- 已在线的旧 `POST /tasks` 继续由 `modules/task/legacy/` 服务旧扩展。
- 部署新网关后才能在线提供 `/tasks/workspace`；发布包含 Side Panel 的新扩展后，终端用户才能使用完整 Shared Workspace 交互。
