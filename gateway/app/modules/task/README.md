# Agent Bridge - Task Module

Task 模块是 Browser Agent 的 HTTP 与状态编排边界：接收当前页面上下文，通过后端
Context Router 选择无状态 Agent，按需注入当前用户的生效 CV，并执行 Quick Insight
或一次 Workspace state transition。

## HTTP 接口

### `POST /tasks/quick-insight`

生成当前页面的只读 `Insight(title, cards)`、后端声明的 Actions，以及稳定的
Workspace 资源描述。下面只展示核心字段，真实响应另外包含回显的 `request` 与完整
`meta`：

```json
{
  "insight": {"title": "Worth Applying", "cards": []},
  "actions": [
    {"id": "analyze", "title": "Analyze"},
    {"id": "tailor_resume", "title": "Tailor Resume"},
    {"id": "write_cover_letter", "title": "Generate Cover Letter"},
    {"id": "ask_more", "title": "Ask More"}
  ],
  "workspace": {
    "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
    "default_action_id": "analyze"
  },
  "protocol_version": 2
}
```

Quick Insight 不创建 Workspace Message 或 Artifact。岗位页面返回 typed score/details/text
cards；普通页面摘要的 Markdown 会由 Gateway 转成经过净化的 `body_html`，供 Quick
Insight 浮层渲染。

### `POST /tasks/workspace`

执行一次无状态 Workspace transition。请求使用 Pydantic discriminated union，由
`trigger` 区分两种互斥输入。

用户消息：

```json
{
  "trigger": "user_message",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前标签页重新采集的完整 JD",
  "pageText": "当前页面可见文字",
  "imageText": "图片文字线索",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "actionId": "tailor_resume",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null},
  "message": "请生成一版针对这个岗位的简历。"
}
```

Quick Insight Action 把 `trigger` 改为 `quick_insight_action`，且禁止发送 `message`。
`ask_more` 只打开 Workspace，不调用该接口。公开请求不接受客户端指定 `agent`。

响应始终返回经过完整校验的 next state；Extension 不在本地 append Assistant Message：

```json
{
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "selected_action_id": "tailor_resume",
  "result_type": "create_artifact",
  "histories": [
    {
      "id": "00000000-0000-0000-0000-000000000001",
      "role": "user",
      "content": "请生成一版针对这个岗位的简历。",
      "action_id": "tailor_resume",
      "created_at": "2026-07-20T10:00:00Z",
      "attachments": []
    },
    {
      "id": "00000000-0000-0000-0000-000000000002",
      "role": "assistant",
      "content": "已生成一版针对该岗位的简历。",
      "action_id": "tailor_resume",
      "created_at": "2026-07-20T10:00:00Z",
      "attachments": [
        {
          "id": "00000000-0000-0000-0000-000000000003",
          "artifact_id": "00000000-0000-0000-0000-000000000004",
          "version": 1,
          "type": "cv",
          "title": "Tailored CV",
          "content": "https://browser.buildwithyang.com"
        }
      ]
    }
  ],
  "artifacts": {
    "cv": {
      "id": "00000000-0000-0000-0000-000000000004",
      "type": "cv",
      "version": 1,
      "title": "Tailored CV",
      "draft": "完整 Markdown",
      "attachment": {
        "id": "00000000-0000-0000-0000-000000000003",
        "artifact_id": "00000000-0000-0000-0000-000000000004",
        "version": 1,
        "type": "cv",
        "title": "Tailored CV",
        "content": "https://browser.buildwithyang.com"
      }
    },
    "cover_letter": null
  },
  "meta": {
    "id": "00000000-0000-0000-0000-000000000005",
    "created_at": "2026-07-20T10:00:00Z",
    "status": "completed",
    "input_chars": 1200,
    "model": "configured-model",
    "started_at": "2026-07-20T10:00:00Z",
    "finished_at": "2026-07-20T10:00:01Z",
    "duration_ms": 1000
  },
  "protocol_version": 2
}
```

`Artifact.attachment` 必须与 histories 中最后一个同类型 Attachment 完全相等，且
`Artifact.version` 必须等于该 Attachment 的 `version`。

`result_type` 只有 `reply`、`create_artifact`、`update_artifact`。Workspace 的 Message、
Artifact draft 和 Cover Letter Attachment 都是 Markdown；Gateway 把它们当作不透明
文本传输，不生成 Workspace HTML、sections 或 document。

## Action 与 Agent 编排

Workspace Action 是强意图提示，不是强制产物命令。用户消息路径的路由优先级是：

```text
当前用户消息 > 当前 Action > 完整历史 > General QA
```

因此选中 `tailor_resume` 后询问“哪段经历最值得突出？”只返回建议；明确要求生成或
重写简历时才创建或更新 CV Artifact。

LinkedIn / Indeed 的 `JobMatchAgent` 是 Facade / Mediator，并协调四个 Strategy：

- `JobAnalysisAgent`：岗位匹配、招聘重点、技能差距，只返回 reply。
- `ResumeTailoringAgent`：简历建议，或完整 CV draft。
- `CoverLetterAgent`：求职信建议，或完整 Cover Letter draft。
- `GeneralQAAgent`：开放追问，只返回 reply。

Quick Insight 的 `analyze`、`tailor_resume`、`write_cover_letter` 是确定性命令，跳过
IntentRouter 并直接调用对应 Specialist；结果不满足 Action 的固定矩阵时整轮失败。
详细执行层约束见 [`agents/job_match/README.md`](../../agents/job_match/README.md)。

## Workspace state

- `histories` 是完整时间线；所有 Message 由 Gateway 生成 UUID 与 UTC `created_at`。
- `artifacts` 必须恰好包含可空的 `cv`、`cover_letter` 两个 key。
- 每种 Artifact 只携带最新完整快照；同类型更新复用 Artifact ID 并将版本加 1。
- 每次产物 create/update 都在本轮 Assistant Message 中增加一个不可变 Attachment。
- Cover Letter Attachment 保存完整 Markdown，因此旧版本仍可在本地历史中查看和复制。
- CV Attachment 当前由 Gateway 指向固定测试 URL `https://browser.buildwithyang.com`；
  draft 会参与下一轮修改，但该 URL 尚不是真实、私有、版本化的 CV 预览。

输入容量：

- `user_message` 最多携带 9 条 history；当前 message 占第 10 个输入槽位。
- `quick_insight_action` 最多携带 10 条 history。
- 合法请求产生的最后一条 Assistant Message 可以让响应 histories 达到 11 条；之后
  Extension 与 Gateway 都禁止继续发送或自动生成。
- 用户文本单条最多 10,000 字符；Assistant 文本和 Artifact draft 最多 100,000 字符。

Gateway 会校验 Message / Attachment / Artifact ID 唯一性、引用关系、类型、版本和最新
快照一致性。任何失败都发生在 next state 应用前，不返回部分 history 或部分 Artifact。

## 协议版本 2

两个新版接口的每个 `POST` 都必须携带：

```http
X-Agent-Bridge-Protocol-Version: 2
```

协议 middleware 在路由、Session、鉴权和请求体解析前执行。Header 缺失、重复、非法或
不等于 `2` 时返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/2
X-Agent-Bridge-Protocol-Version: 2
```

响应 body 包含 `code=extension_update_required`、`required_protocol_version=2` 和扩展
更新地址。通过版本 gate 的成功与业务错误响应也都返回当前协议 Header；成功 body
另外包含 `protocol_version: 2`。协议整数与 `manifest.json` 发布版本相互独立。

### Retired `POST /tasks`

精确 `POST /tasks` 只是升级 shim：不读取请求体、不解析旧 schema、不执行身份检查、
不调用 `TaskService` 或 Agent，并始终返回同一个 `426`。`legacy/api.py` 只保留
middleware wiring 变化时的防御性 raw fallback，不保留旧生成逻辑。

## Context Routing 与资源身份

`router.py` 根据页面上下文选择内部 Agent：

- LinkedIn / Indeed host 且选区达到 `MIN_JOB_CONTENT_CHARS`：`job_match`。
- 其他页面或不完整岗位上下文：`summary_page`。

`normalize_resource_url()` 把 LinkedIn `/jobs/view/{id}` 与 `currentJobId` 统一成同一资源，
把 Indeed `jk` / `vjk` 统一成地区 host 下的 `viewjob?jk=...`。普通 URL 移除 fragment 与
`utm_*`，稳定排序其余 query。Workspace 会从当前 `url` 重新计算并校验 `resourceUrl`。

## 分层与持久化边界

- `api.py`：路由、参数、身份解析和 HTTP 错误映射。
- `protocol.py`：协议常量、426 工厂和 Router 之前执行的 middleware。
- `service.py`：Agent 分发、CV 注入、Workspace reducer、限流和 task record 编排。
- `repo.py`：`task_records` 持久化。
- `router.py`：Context Router 与资源 URL 归一化纯函数。
- `legacy/api.py`：旧入口的 raw 426 fallback。

本期没有服务端 Thread 或 Artifact Repository；Workspace histories / artifacts 由 Extension
在当前 Chrome 配置中保存并随每次请求回传。数据库配置存在时，Gateway 仍会写既有
task record（包含可能敏感的页面、Prompt 与模型结果）；部署方必须配置访问权限、脱敏
与保留周期。
