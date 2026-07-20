# Agent Bridge - Task Module

Task 模块是浏览器扩展与无状态 Agent 之间的 HTTP、协议和状态编排边界。它接收当前页面
上下文，为认证用户注入当前生效 CV，并提供两个不同的接口：Quick Insight 返回普通
JSON；Workspace 使用 protocol v3 NDJSON 增量返回。

## HTTP 接口

两个接口都要求：

```http
X-Agent-Bridge-Protocol-Version: 3
```

### `POST /tasks/quick-insight`

Quick Insight 是一次普通 JSON 请求，用于生成只读页面洞察、可用 Actions 和稳定的
Workspace 资源身份。它不会创建 Workspace Message 或 Artifact。

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
  "protocol_version": 3
}
```

岗位页面返回 typed score/details/text cards；普通页面摘要的 Markdown 由 Gateway 转成
经过净化的 `body_html`，供页面浮层渲染。

### `POST /tasks/workspace`

Workspace 请求必须发送：

```http
Accept: application/x-ndjson
Content-Type: application/json
X-Agent-Bridge-Protocol-Version: 3
```

普通用户消息示例：

```json
{
  "trigger": "user_message",
  "operationId": "00000000-0000-0000-0000-000000000001",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前标签页重新采集的完整 JD",
  "pageText": "当前页面可见文字",
  "imageText": "图片文字线索",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "actionId": "analyze",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null},
  "message": "这个岗位最看重什么？"
}
```

Quick Insight Action 把 `trigger` 改为 `quick_insight_action`，不发送 `message`。
`ask_more` 只打开 Workspace，不调用该接口。公开请求不接受客户端指定 Agent。

成功响应是 `application/x-ndjson`，每行一个严格事件，`operation_id` 与请求的
`operationId` 相同，`sequence` 从 0 开始严格递增：

```ndjson
{"type":"started","operation_id":"00000000-0000-0000-0000-000000000001","sequence":0,"created_at":"2026-07-20T10:00:00Z"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":1,"stage":"routing"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":2,"stage":"generating_reply"}
{"type":"delta","operation_id":"00000000-0000-0000-0000-000000000001","sequence":3,"text":"这个岗位最看重"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":4,"stage":"finalizing"}
{"type":"completed","operation_id":"00000000-0000-0000-0000-000000000001","sequence":5,"response":{"resource_url":"https://www.linkedin.com/jobs/view/4442412976","selected_action_id":"analyze","result_type":"reply","histories":[{"id":"00000000-0000-0000-0000-000000000010","role":"user","content":"这个岗位最看重什么？","action_id":"analyze","created_at":"2026-07-20T10:00:00Z","attachments":[]},{"id":"00000000-0000-0000-0000-000000000011","role":"assistant","content":"这个岗位最看重端到端交付能力。","action_id":"analyze","created_at":"2026-07-20T10:00:01Z","attachments":[]}],"artifacts":{"cv":null,"cover_letter":null},"meta":{"id":"00000000-0000-0000-0000-000000000012","created_at":"2026-07-20T10:00:00Z","status":"completed","input_chars":1200,"model":"configured-model","started_at":"2026-07-20T10:00:00Z","finished_at":"2026-07-20T10:00:01Z","duration_ms":1000},"protocol_version":3}}
```

`completed.response` 带完整 canonical histories、artifacts 和 execution meta。`failed`
是唯一失败终态，包含稳定 `code`、用户安全的 `message` 和
`recoverable`，不会携带部分 next state。

## 增量与原子状态

- 普通 reply 会在 `generating_reply` 期间发送增量 Markdown `delta`。
- CV / Cover Letter 只发送 `generating_artifact` status；该 status 才带
  `artifact_type`。Artifact 草稿绝不作为 delta 暴露。
- Artifact 只在成功的 `completed.response` 中以完整 draft 和 terminal Attachment 出现。
- `started`、`status`、`delta` 只是 transient 展示；只有完成终态进入 reducer 和持久化。
- Extension 乐观显示用户消息，但不会提前写入 canonical history。
- 模型失败、非法输出、断流、超时或客户端断开都不会 append histories 或更新 Artifact。

Gateway 在 complete ChatResult 通过校验后一次性分配 UUID、UTC 时间、Artifact 版本和
Attachment，再生成 canonical next state。`Artifact.attachment` 必须等于 histories 中最后
一个同类型 Attachment；同类型更新复用 Artifact ID 并将版本加 1。

## Job Match 执行

Job Match Workspace 使用 OpenAI-compatible **Chat Completions**，不使用 Responses API。
用户消息先由 `ChatPlanner` 选择一个 Specialist 和输出模式；Quick Insight 的
`analyze`、`tailor_resume`、`write_cover_letter` 使用确定性计划。

- `JobAnalysisAgent`：岗位分析，只生成 reply。
- `ResumeTailoringAgent`：建议 reply 或完整 CV Artifact。
- `CoverLetterAgent`：建议 reply 或完整 Cover Letter Artifact。
- `GeneralQAAgent`：开放追问，只生成 reply。

当前用户请求优先于所选 Action。选中 `tailor_resume` 后询问经历取舍会得到建议；明确
要求生成或重写简历时才进入 Artifact 模式。执行层详情见
[`agents/job_match/README.md`](../../agents/job_match/README.md)。

## Workspace state 与容量

- `histories` 是完整 canonical 时间线；所有 Message 由 Gateway 生成 UUID 和 UTC 时间。
- `artifacts` 固定包含可空的 `cv` 与 `cover_letter`；每类只携带最新完整快照。
- `user_message` 最多携带 9 条 history；当前消息占第 10 个输入槽位。
- `quick_insight_action` 最多携带 10 条 history。
- 成功终态最多包含 11 条消息；达到上限后 Extension 不再发送。
- 用户文本最多 10,000 字符；Assistant Markdown 与 Artifact draft 最多 100,000 字符。

本期没有服务端 Thread 或 Artifact Repository。Extension 按 owner 与规范化资源把
canonical histories / artifacts 保存到当前 Chrome 配置，并在下次请求完整回传。

## 协议不兼容与代理部署

协议 middleware 在路由、Session、鉴权和请求体解析前执行。Header 缺失、重复、非法，
或发送旧版本时都会返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/3
X-Agent-Bridge-Protocol-Version: 3
```

响应包含 `code=extension_update_required`、`required_protocol_version=3` 和扩展更新地址。
客户端应更新扩展并重试；协议整数与 `manifest.json` 发布版本相互独立。旧
`POST /tasks` 只保留同样的升级提示，不执行 Agent。

Gateway 自身返回 `X-Accel-Buffering: no`。Nginx 部署还必须对精确路径
`/api/tasks/workspace` 设置 `proxy_buffering off` 和 `proxy_cache off`，否则 reply delta
可能被代理聚合后才到浏览器。普通 `/api/` 仍使用既有前缀转发。

## 模块边界与隐私

- `api.py`：路由、身份、HTTP 错误映射与 NDJSON response boundary。
- `protocol.py`：protocol v3 gate 与 426 响应。
- `stream_schema.py`：严格事件 schema 与单行 NDJSON 编码。
- `service.py`：Agent 分发、CV 注入、原子 reducer、限流和任务指标。
- `repo.py`：`task_records` 持久化。
- `router.py`：根据当前页面选择内部无状态 Agent，并规范化资源 URL。

数据库启用时，Gateway 会记录既有 task record。部署方必须为可能包含页面、Prompt 或
模型结果的字段配置访问控制、脱敏与保留周期；日志不得记录页面正文、完整 prompt、模型
响应、bearer token 或 provider key。
