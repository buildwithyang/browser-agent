# Agent Bridge - Task Module

Task 模块是浏览器扩展与无状态 Agent 之间的 HTTP、协议和状态编排边界。它接收当前页面
上下文，为认证用户注入当前生效 CV，并提供两个接口：Quick Insight 返回普通 JSON；
Workspace 使用 protocol v4 NDJSON 增量返回。

## HTTP 接口

两个接口都要求：

```http
X-Agent-Bridge-Protocol-Version: 4
```

### `POST /tasks/quick-insight`

Quick Insight 是一次普通 JSON 请求，用于生成只读页面洞察、本地化可编辑 Prompt
Shortcuts 和稳定的 Workspace 资源身份。它不会创建 Workspace Message 或 Artifact。

```json
{
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前标签页重新采集的完整 JD",
  "pageText": "当前页面可见文字",
  "imageText": "图片文字线索",
  "intent": "JOB PAGE INTENT",
  "lang": "zh"
}
```

岗位页面的成功响应包含四个 Shortcut；普通页面只有 Prompt 为空的 `ask_more`：

```json
{
  "request": {
    "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
    "title": "Full Stack Engineer",
    "selectedText": "当前标签页重新采集的完整 JD",
    "pageText": "当前页面可见文字",
    "imageText": "图片文字线索",
    "intent": "JOB PAGE INTENT",
    "lang": "zh"
  },
  "insight": {"title": "岗位匹配", "cards": []},
  "shortcuts": [
    {
      "id": "analyze",
      "title": "分析岗位",
      "prompt": "请分析这个岗位真正看重的能力，并以 Markdown 表格逐项对比“JD 要求”和“匹配情况”。表格后总结我的匹配优势、核心差距，以及是否值得申请，并给出明确结论和理由。"
    },
    {
      "id": "tailor_resume",
      "title": "定制简历",
      "prompt": "请结合当前 JD 和我的简历，先指出最值得强化的经历及你计划修改的部分。暂时不要生成新简历，等我确认后再生成。"
    },
    {
      "id": "write_cover_letter",
      "title": "撰写求职信",
      "prompt": "请结合当前 JD 和我的简历，生成一封简洁、具体、不过度夸张的求职信，重点突出与岗位最相关的经历。"
    },
    {"id": "ask_more", "title": "继续提问", "prompt": ""}
  ],
  "workspace": {
    "resource_url": "https://www.linkedin.com/jobs/view/4442412976"
  },
  "meta": {
    "id": "00000000-0000-0000-0000-000000000020",
    "created_at": "2026-07-21T10:00:00Z",
    "status": "completed",
    "input_chars": 1200,
    "model": "configured-model",
    "started_at": "2026-07-21T10:00:00Z",
    "finished_at": "2026-07-21T10:00:01Z",
    "duration_ms": 1000
  },
  "protocol_version": 4
}
```

岗位页面返回 typed score/details/text cards；普通页面摘要的 Markdown 由 Gateway 转成
经过净化的 `body_html`，供页面浮层渲染。Shortcut 点击只填充输入框，不调用 Workspace。

### `POST /tasks/workspace`

Workspace 请求必须发送：

```http
Accept: application/x-ndjson
Content-Type: application/json
X-Agent-Bridge-Protocol-Version: 4
```

每次请求都必须包含用户最终确认的 `message`，不会携带 Shortcut id 或任何 Action 路由
参数：

```json
{
  "operationId": "00000000-0000-0000-0000-000000000001",
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前标签页重新采集的完整 JD",
  "pageText": "当前页面可见文字",
  "imageText": "图片文字线索",
  "intent": "JOB PAGE INTENT",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "histories": [],
  "artifacts": {"cv": null, "cover_letter": null},
  "message": "请分析这个岗位真正看重的能力……"
}
```

成功响应是 `application/x-ndjson`，每行一个严格事件，`operation_id` 与请求的
`operationId` 相同，`sequence` 从 0 开始严格递增：

```ndjson
{"type":"started","operation_id":"00000000-0000-0000-0000-000000000001","sequence":0,"created_at":"2026-07-21T10:00:00Z"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":1,"stage":"routing"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":2,"stage":"generating_reply"}
{"type":"delta","operation_id":"00000000-0000-0000-0000-000000000001","sequence":3,"text":"| JD 要求 | 匹配情况 |"}
{"type":"status","operation_id":"00000000-0000-0000-0000-000000000001","sequence":4,"stage":"finalizing"}
{"type":"completed","operation_id":"00000000-0000-0000-0000-000000000001","sequence":5,"response":{"resource_url":"https://www.linkedin.com/jobs/view/4442412976","result_type":"reply","histories":[{"id":"00000000-0000-0000-0000-000000000010","role":"user","content":"请分析这个岗位真正看重的能力……","created_at":"2026-07-21T10:00:00Z","attachments":[]},{"id":"00000000-0000-0000-0000-000000000011","role":"assistant","content":"| JD 要求 | 匹配情况 |\n| --- | --- |\n| 端到端交付 | 匹配 |","created_at":"2026-07-21T10:00:01Z","attachments":[]}],"artifacts":{"cv":null,"cover_letter":null},"meta":{"id":"00000000-0000-0000-0000-000000000012","created_at":"2026-07-21T10:00:00Z","status":"completed","input_chars":1200,"model":"configured-model","started_at":"2026-07-21T10:00:00Z","finished_at":"2026-07-21T10:00:01Z","duration_ms":1000},"protocol_version":4}}
```

`completed.response` 带完整 canonical histories、artifacts 和 execution meta。`failed`
是唯一失败终态，包含稳定 `code`、用户安全的 `message` 和 `recoverable`，不会携带部分
next state。

## Intent Router 与 Specialist 边界

每条 Workspace 消息都由 `IntentRouter` 根据以下证据重新路由：

```text
current message > current Artifacts > histories
```

公开请求不能指定 Agent、Specialist 或输出模式。Router 选择 Specialist Strategy、
`reply | artifact` 与执行指令；具体 Specialist 才生成内容。Tailor Resume 的 Shortcut 首先要求修改
计划，因此必须先返回 reply，用户确认后才可生成或更新 CV。Cover Letter 的 Shortcut
明确请求成稿，因此可直接生成纯文本、可复制的 Artifact；后续“短一点”等消息会更新它。

Analyze 必须逐项对比重要要求，Markdown 表格只能有以下两个 comparison columns：

```markdown
| JD 要求 | 匹配情况 |
| --- | --- |
```

英文只能使用 `JD Requirement | Match`。表格后再说明优势、核心差距、申请风险与明确建议。

## 增量与原子状态

- 普通 reply 会在 `generating_reply` 期间发送增量 Markdown `delta`。
- CV / Cover Letter 只发送 `generating_artifact` status；Artifact draft 不作为 delta 暴露。
- Artifact 只在成功的 `completed.response` 中以完整 draft 和 terminal Attachment 出现。
- Gateway 与 Extension 都校验 `routing -> generating_* -> finalizing -> completed` 生命周期。
- `started`、`status`、`delta` 只是 transient 展示；只有完成终态进入 reducer 和持久化。
- 模型失败、非法输出、断流、超时或客户端断开都不会 append histories 或更新 Artifact。

Gateway 在 complete ChatResult 通过校验后一次性分配 UUID、UTC 时间、Artifact 版本和
Attachment，再生成 canonical next state。同类型更新复用 Artifact ID 并将版本加 1。

## Workspace state 与容量

- `histories` 是完整 canonical 时间线；所有 Message 由 Gateway 生成 UUID 和 UTC 时间。
- `artifacts` 固定包含可空的 `cv` 与 `cover_letter`；每类只携带最新完整快照。
- 轮数只统计 `role=user`；第 10 次用户发送允许，第 11 次拒绝。
- pure-v4 history 必须是完整、按顺序排列的 User/Assistant pair；请求最多携带 9 个 pair，
  terminal response 最多携带 10 个 pair / 20 条 history。
- Extension 的 `WORKSPACE_GET` 丢弃精确旧本地 schema/mapping 并返回未连接；下一次 Quick
  Insight seed 才创建全新 v3 Workspace，不向 Gateway 发送旧历史。
- 失败、取消或非法终态不提交 canonical history，因此不消耗轮数。
- 达到上限后客户端仍可展示历史、Attachment 和复制控件。
- 用户文本最多 10,000 字符；Assistant Markdown 与 Artifact draft 最多 100,000 字符。

本期没有服务端 Thread 或 Artifact Repository。Extension 按 owner 与规范化资源把
canonical histories / artifacts 保存到当前 Chrome 配置，并在下次请求完整回传。

## 协议不兼容与代理部署

协议 middleware 在路由、Session、鉴权和请求体解析前执行。Header 缺失、重复、非法，
或发送旧版本时都会返回：

```http
HTTP/1.1 426 Upgrade Required
Upgrade: Agent-Bridge/4
X-Agent-Bridge-Protocol-Version: 4
```

响应包含 `code=extension_update_required`、`required_protocol_version=4` 和扩展更新地址。
客户端应更新扩展并重试；协议整数与 `manifest.json` 发布版本相互独立。旧 `POST /tasks`
只保留同样的升级提示，不执行 Agent。

Gateway 自身返回 `X-Accel-Buffering: no`。Nginx 部署还必须对精确路径
`/api/tasks/workspace` 设置 `proxy_buffering off` 和 `proxy_cache off`，否则 reply delta
可能被代理聚合后才到浏览器。

## 模块边界与隐私

- `api.py`：路由、身份、HTTP 错误映射与 NDJSON response boundary。
- `protocol.py`：protocol v4 gate 与 426 响应。
- `stream_schema.py`：严格事件 schema 与单行 NDJSON 编码。
- `service.py`：Agent 分发、CV 注入、原子 reducer、限流和任务指标。
- `repo.py`：`task_records` 持久化。
- `router.py`：根据当前页面选择内部无状态 Agent，并规范化资源 URL。

数据库启用时，Gateway 会记录既有 task record。失败、取消和断流记录默认只包含运营指标，
不会保存 URL、标题、页面正文、Prompt 或模型结果；成功记录仍可能包含这些任务明细。
部署方必须为成功明细配置访问控制、脱敏与保留周期；日志不得记录页面正文、完整 prompt、
模型响应、bearer token 或 provider key。
