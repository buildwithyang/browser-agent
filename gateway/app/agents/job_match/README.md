# Job Match Agent

`job_match` 是 LinkedIn / Indeed 岗位场景的无状态执行层。它把 Quick Insight 与
Workspace 聊天分成两个入口，并由 `JobMatchAgent` 统一协调意图路由和专业
Specialist。消息、Artifact 版本、UUID、时间戳和持久化都不由 Agent 管理。

## 公开接口

`JobMatchAgent` 同时实现 `app.agents.base` 中的两个 `Protocol`：

```python
class QuickInsightAgent(Protocol):
    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]: ...
    def available_actions(self, context: AgentContext) -> list[Action]: ...

class WorkspaceAgent(Protocol):
    def handle_chat(
        self, context: WorkspaceAgentContext
    ) -> AgentExecution[ChatResult]: ...
```

- `quick_insight()` 返回用于页面浮层的 typed `Insight`，不创建 Artifact。
- `available_actions()` 声明当前岗位可用的 Action。
- `handle_chat()` 返回 `reply | create_artifact | update_artifact`，不修改请求 state。

`JobMatchAgent` 是 Workspace 的 **Facade / Mediator**。它只协调一次请求，不缓存
用户简历、页面内容、历史或 Artifact。

## 代码结构

```text
job_match/
├── agent.py                 # Facade / Mediator；结果矩阵与 create/update 归一化
├── context.py               # 不可变的请求级 JobChatContext
├── quick_insight.py         # 岗位匹配 Quick Insight 与 Actions
├── router.py                # 结构化 IntentRouter；最多一次纠错重试
└── specialists/
    ├── base.py              # Strategy 接口、Template Method 与结构化结果解析
    ├── analysis.py          # 岗位分析；只允许 reply
    ├── resume.py            # 简历建议或完整 CV 草稿
    ├── cover_letter.py      # 求职信建议或完整 Cover Letter 草稿
    └── general_qa.py        # 开放追问；只允许 reply
```

`StructuredJobMatchSpecialist` 用 Template Method 固定 Prompt 构建、模型调用、结构化
解析和合法结果校验；具体 Strategy 只声明场景指令与允许生成的 Artifact 类型。

## 两条 Workspace 路径

### 用户消息

```text
current message + selected Action + histories + artifacts
  -> IntentRouter
  -> exactly one Specialist
  -> JobMatchAgent validates the result
  -> reply / create_artifact / update_artifact
```

路由证据优先级固定为：

```text
当前用户消息 > 当前 Action > 完整历史 > General QA
```

Action 是强意图提示，不是强制产物命令。例如选中 `tailor_resume` 后询问“哪段经历
最值得突出？”应返回普通建议；只有用户明确要求生成或重写简历时才返回 CV 草稿。

### Quick Insight Action

Quick Insight 的点击是确定性命令，不调用 `IntentRouter`：

| Action | Specialist | 合法结果 |
| --- | --- | --- |
| `analyze` | `JobAnalysisAgent` | `reply` |
| `tailor_resume` | `ResumeTailoringAgent` | CV `artifact_draft` |
| `write_cover_letter` | `CoverLetterAgent` | Cover Letter `artifact_draft` |
| `ask_more` | 不调用后端 Agent | 只打开 Workspace 并聚焦输入框 |

点击 Resume / Cover Letter 会立即创建对应 Artifact；同类型 Artifact 已存在时会更新。
Quick Action 仍使用当前完整 histories 和 artifacts，但不会伪造 User Message。

## Specialist 结果矩阵

Specialist 只返回候选结果 `reply | artifact_draft`。最终 create/update 由
`JobMatchAgent` 根据同类型 Artifact 是否存在统一决定。

| Specialist | `reply` | `artifact_draft` |
| --- | --- | --- |
| `JobAnalysisAgent` | 是 | 否 |
| `ResumeTailoringAgent` | 是 | 是，仅 `cv` |
| `CoverLetterAgent` | 是 | 是，仅 `cover_letter` |
| `GeneralQAAgent` | 是 | 否 |

解析器兼容模型在 JSON 字符串中未转义的 Markdown 换行；除此之外，非法 JSON、
未知字段、错误 Artifact 类型或违反矩阵的结果都会失败，不允许降级成看似成功的
回复。`IntentRouter` 第一次解析失败会纠错重试一次；第二次失败即终止本轮。

## 状态边界

Agent 返回完整 Markdown 草稿，但不负责：

- append `HistoryMessage`；
- 生成 Message / Artifact / Attachment UUID 与 UTC 时间；
- 分配 Artifact 版本；
- 生成 CV Attachment URL；
- 写 Chrome storage、Thread 或 Artifact 数据库。

这些状态转换由 `modules/task/service.py` 的 reducer 在完整校验后一次性完成。Gateway
当前只记录既有 task record；Workspace histories 和 artifacts 由 Extension 按用户与
规范化资源保存在本地。本期 CV Attachment 由 Gateway 暂时指向固定测试预览地址，
不代表真实 CV 已托管或版本化。

认证用户的生效 CV 由 `TaskService` 按请求注入；匿名自部署没有用户级 Resume Service，
`JobMatchAgent` 会在每次 Quick Insight 或 Workspace 请求中重新读取
`AGENT_BRIDGE_CV_PATH`，不在 Agent 实例上缓存文本。

## 扩展新能力

新增 Specialist 时：

1. 在 `SpecialistId` 增加稳定 id。
2. 实现 `JobMatchSpecialist` Strategy，并声明允许的 Artifact 类型。
3. 注册到 `JobMatchAgent._build_specialists()`。
4. 更新 Facade 的合法结果矩阵；若支持 Quick Action，再增加确定性映射。
5. 为路由优先级、非法输出和 state 不变性增加测试。

Agent 必须继续保持无状态；任何按用户区分的数据只能通过请求级 Context 注入。
