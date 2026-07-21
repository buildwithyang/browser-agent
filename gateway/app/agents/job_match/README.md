# Job Match Agent

`job_match` 是 LinkedIn / Indeed 岗位场景的无状态执行层。`JobMatchAgent` 作为
Facade / Mediator 协调 Quick Insight、每轮 Workspace planning 与 Specialist Strategy；
消息、Artifact 版本、UUID、时间戳与持久化仍由 `modules/task` 管理。

## 公开能力

- `quick_insight()` 返回页面浮层使用的 typed `Insight` 与本地化 Prompt Shortcuts，不创建
  Message 或 Artifact。
- `stream_chat()` 为每条用户消息运行 Planner，依次产生进度、可见 reply delta 和一个
  完整终态候选结果。
- `handle_chat()` 只保留给同步调用边界，内部消费同一 stream，不维护第二套生成逻辑。

Agent 不缓存用户 CV、页面正文、histories 或 artifacts。认证用户的生效 CV 由
`TaskService` 按请求注入；匿名自部署通过可选 `WorkspaceContextPreparer` 在 `started`
之前从 `AGENT_BRIDGE_CV_PATH` 读取。缺失或不可解析的本地 PDF 因此返回普通 HTTP 错误，
不会先建立一个必然失败的 Workspace stream。

Agent 只接收 pure-v4 canonical history：完整的 User/Assistant pair，最多 10 个 User turn /
20 条 Message。旧本地 Workspace schema 由 Extension 丢弃，不进入 Planner 或 Specialist。

## 结构

```text
job_match/
├── agent.py                 # Facade / Mediator；stream orchestration 与结果归一化
├── context.py               # 不可变的请求级 JobChatContext
├── planner.py               # ChatPlanner；选择 Specialist 与 reply/artifact 输出模式
├── quick_insight.py         # 岗位 Quick Insight 与 Prompt Shortcuts
└── specialists/
    ├── base.py              # Strategy 接口与流式 Template Method
    ├── analysis.py          # 岗位分析；只允许 reply
    ├── resume.py            # 简历建议或完整 CV draft
    ├── cover_letter.py      # 求职信建议或完整 Cover Letter draft
    └── general_qa.py        # 开放追问；只允许 reply
```

所有模型调用都走 OpenAI-compatible **Chat Completions**。Workspace Specialist 通过
`chat.completions.create(..., stream=True)` 返回 raw text chunk；普通回复和 CV 使用
Markdown，Cover Letter 使用可直接复制的纯文本；不使用 Responses API，也不要求模型
生成 JSON transport envelope。

## Prompt Shortcut 与 Planner 边界

Quick Insight 只声明本地化、可编辑的 composer draft。Shortcut 点击不会调用 Agent，发送
时也不会提交 Shortcut id。每一条最终用户消息都经过同一规划路径：

```text
current message + current artifacts + histories
  -> ChatPlanner selects Specialist + output mode
  -> exactly one Specialist streams raw text
  -> JobMatchAgent validates the complete result
  -> TaskService atomically builds completed.response
```

Planner 的证据优先级严格为：

```text
current message > current Artifacts > histories
```

Planner 只拥有 Specialist 与 `reply | artifact` 的选择权，不生成正文。具体 Strategy 只拥有
本场景内容生成权，不决定 HTTP、wire protocol、Message/Attachment identity 或 persistence。
这是 Facade + Strategy 的边界，避免 UI 控件成为后端隐藏路由参数。

- Analyze Prompt 要求分析，因此 Planner 选择 `JobAnalysisAgent + reply`。
- Tailor Resume Prompt 只要求先给修改计划，因此首轮必须是 `ResumeTailoringAgent + reply`；
  用户确认生成后，后续消息才进入 CV Artifact create/update。
- Cover Letter Prompt 明确要求成稿，因此进入 `CoverLetterAgent + artifact`；后续“短一点”
  等编辑指令结合当前 Artifact 进入 update。
- 开放问题在没有更强证据时进入 `GeneralQAAgent + reply`。

## Analyze 输出契约

`JobAnalysisAgent` 必须先逐项比较每一条重要 JD 要求。中文 Markdown 表格只能有以下两个
comparison columns：

```markdown
| JD 要求 | 匹配情况 |
| --- | --- |
```

英文只能使用：

```markdown
| JD Requirement | Match |
| --- | --- |
```

不能增加序号、权重或备注等第三列。表格之后再叙述最强匹配、核心差距、真实 fit、申请风险，
并给出是否值得申请的明确结论和理由。

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
iterator。具体 Strategy 提供场景指令、允许的输出模式和产物格式。

模型输出契约是 raw text：

- reply 模式只输出完整 Markdown 对话回答；
- CV Artifact 只输出完整 Markdown 简历正文；
- Cover Letter Artifact 只输出带自然段落的纯文本，不使用标题、列表、强调、分隔线或
  代码围栏等 Markdown 语法；
- 不增加代码围栏、JSON 对象、transport metadata 或 Artifact 外的完成说明。

Planner 会显式读取当前 Artifact 状态。用户对已有产物发出“短一点”“更自信”“翻译成
英文”等直接编辑指令时进入 Artifact 更新模式；询问“应该怎么改”时仍返回普通回复。

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
