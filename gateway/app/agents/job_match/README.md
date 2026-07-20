# Job Match Agent

`job_match` 是 LinkedIn / Indeed 岗位场景的无状态执行层。`JobMatchAgent` 作为
Facade / Mediator 统一协调 Quick Insight、Workspace 计划和 Specialist Strategy；消息、
Artifact 版本、UUID、时间戳与持久化仍由 `modules/task` 管理。

## 公开能力

- `quick_insight()` 返回页面浮层使用的 typed `Insight`，不创建 Message 或 Artifact。
- `available_actions()` 声明当前岗位可用的 Action。
- `stream_chat()` 依次产生进度、可见 reply delta 和一个完整终态候选结果。
- `handle_chat()` 只保留给同步调用边界，内部消费同一 stream，不维护第二套生成逻辑。

Agent 不缓存用户 CV、页面正文、histories 或 artifacts。认证用户的生效 CV 由
`TaskService` 按请求注入；匿名自部署每次从 `AGENT_BRIDGE_CV_PATH` 读取。

## 结构

```text
job_match/
├── agent.py                 # Facade / Mediator；stream orchestration 与结果归一化
├── context.py               # 不可变的请求级 JobChatContext
├── planner.py               # ChatPlanner；选择 Specialist 与 reply/artifact 输出模式
├── quick_insight.py         # 岗位 Quick Insight 与 Actions
└── specialists/
    ├── base.py              # Strategy 接口与流式 Template Method
    ├── analysis.py          # 岗位分析；只允许 reply
    ├── resume.py            # 简历建议或完整 CV draft
    ├── cover_letter.py      # 求职信建议或完整 Cover Letter draft
    └── general_qa.py        # 开放追问；只允许 reply
```

所有模型调用都走 OpenAI-compatible **Chat Completions**。Workspace Specialist 通过
`chat.completions.create(..., stream=True)` 返回 raw Markdown chunk；不使用 Responses API，
也不要求模型生成 JSON transport envelope。

## 用户消息与 Quick Action

用户消息路径：

```text
current message + selected Action + histories + artifacts
  -> ChatPlanner selects Specialist + output mode
  -> exactly one Specialist streams raw Markdown
  -> JobMatchAgent validates the complete result
  -> TaskService atomically builds completed.response
```

计划证据优先级为当前用户消息、所选 Action、完整历史和已有 Artifact。Action 是强意图
提示，不覆盖当前用户的明确要求。例如选择 `tailor_resume` 后问“哪段经历最值得突出？”
会进入 reply；明确要求生成或重写简历时才进入 Artifact 模式。

Quick Insight 点击使用确定性计划，不调用 `ChatPlanner`：

| Action | Specialist | 输出模式 |
| --- | --- | --- |
| `analyze` | `JobAnalysisAgent` | reply |
| `tailor_resume` | `ResumeTailoringAgent` | Artifact (`cv`) |
| `write_cover_letter` | `CoverLetterAgent` | Artifact (`cover_letter`) |
| `ask_more` | 不调用后端 Agent | 只打开 Workspace |

同类型 Artifact 已存在时，Facade 生成 update 候选；否则生成 create 候选。

## Streaming 契约

一次成功的 Agent stream 按以下顺序运行：

```text
routing
  -> generating_reply -> reply Markdown deltas
  -> finalizing -> complete reply

routing
  -> generating_artifact(type) -> no draft deltas
  -> finalizing -> complete Artifact draft
```

- reply chunk 会作为 `AgentDelta` 向 Gateway 传递，Side Panel 可增量渲染 Markdown。
- CV / Cover Letter chunk 只在 Agent 内存中累积；wire 只看见带类型的生成状态。
- 空结果、超出 100,000 字符、错误输出模式或非法 Artifact 类型都会终止本轮。
- Specialist 完成后才创建 typed `ReplyResult`、`CreateArtifactResult` 或
  `UpdateArtifactResult`；Gateway reducer 不接受 partial draft。
- Agent 异常或客户端断开时，迭代器会被关闭，TaskService 只记录失败指标。

Artifact 生成完成后，Facade 使用确定性的本地化标题与 Assistant note。完整 draft、
Attachment、Artifact ID 和版本只存在于 Gateway 成功的 `completed.response` 中。

## Specialist 输出边界

`StreamingJobMatchSpecialist` 使用 Template Method 固定四个步骤：校验输出模式、构造
system/user prompt、打开 Chat Completions stream、返回 provider-independent chunk
iterator。具体 Strategy 只提供场景指令和允许的输出模式。

模型输出契约是 raw Markdown：

- reply 模式只输出完整对话回答；
- Artifact 模式只输出完整产物正文；
- 不增加代码围栏、JSON 对象、transport metadata 或 Artifact 外的完成说明。

页面、简历、histories 与 artifacts 均作为不可信参考数据放入 prompt；当前用户消息才是
本轮指令。Agent 不把 provider chunk、prompt 或原始结果写日志。

## 扩展能力

新增 Specialist 时：

1. 在 `SpecialistId` 增加稳定 id，并在 `ChatPlanner` 声明可选计划。
2. 实现 `JobMatchSpecialist` Strategy，明确允许的 `OutputMode`。
3. 注册到 `JobMatchAgent._build_specialists()`。
4. 若能生成 Artifact，增加稳定类型、标题和 create/update 归一化映射。
5. 覆盖计划优先级、status/delta 可见性、非法输出和 state 不变性测试。

新增实现必须继续保持 request-scoped；任何用户相关数据只能通过 Context 注入。
