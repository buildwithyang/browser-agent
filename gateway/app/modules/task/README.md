# Agent Bridge - Task Module

Task 模块负责浏览器任务的一次请求生命周期：接收页面上下文，通过后端 Context Router 选择无状态 Agent，按需注入当前用户简历，执行任务，并在数据库已配置时持久化任务记录。

> 本文描述当前代码契约，不代表云端已经部署 `/tasks/workspace`。新接口上线与 Chrome 扩展发布是独立步骤。

## HTTP 接口

### `POST /tasks/quick-insight`

返回当前页面的 `Insight(title, cards)`、后端声明的 `actions` 和稳定的 `workspace` 描述，不生成 Workspace 文档。

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
  }
}
```

### `POST /tasks/workspace`

执行一次无状态 Workspace 转换。请求携带当前页面、Action、完整共享历史、最新草稿和当前消息：

```json
{
  "url": "https://www.linkedin.com/jobs/search/?currentJobId=4442412976",
  "title": "Full Stack Engineer",
  "selectedText": "当前标签页重新采集的完整 JD",
  "pageText": "当前页面可见文字",
  "imageText": "图片文字线索",
  "lang": "zh",
  "resourceUrl": "https://www.linkedin.com/jobs/view/4442412976",
  "actionId": "tailor_resume",
  "histories": [
    {"role": "user", "content": "这个岗位最看重什么？"},
    {"role": "assistant", "content": "核心是 Agent 和 MCP 经验。"}
  ],
  "currentDocument": {
    "kind": "resume",
    "title": "Tailored Resume",
    "text": "上一轮完整 Markdown"
  },
  "message": "根据刚才的分析突出我的 Go 项目。"
}
```

响应返回**完整的新历史**和最新文档：

```json
{
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "selected_action_id": "tailor_resume",
  "histories": [
    {"role": "user", "content": "这个岗位最看重什么？", "action_id": "analyze"},
    {"role": "assistant", "content": "核心是 Agent 和 MCP 经验。", "action_id": "analyze"},
    {"role": "user", "content": "根据刚才的分析突出我的 Go 项目。", "action_id": "tailor_resume"},
    {"role": "assistant", "content": "已强化 Go 项目和 Agent 经验。", "action_id": "tailor_resume"}
  ],
  "document": {
    "kind": "resume",
    "title": "Tailored Resume",
    "text": "完整 Markdown",
    "html": "<article>...</article>",
    "sections": []
  },
  "meta": {"status": "completed", "model": "configured-model"}
}
```

实际 `HistoryMessage` 还包含网关生成的 `id`、`created_at`，以及产生该消息的 `action_id`。上例省略了部分重复字段以突出状态转换。

扩展用响应中的 `histories` / `document` 整体替换本地状态，不能在客户端自行 append。`ask_more` 同样返回完整历史，但 `document` 为 `null`。

### Legacy `POST /tasks`

线上已发布的旧扩展仍使用 deprecated `POST /tasks`。它的 transport schema 和 adapter 隔离在 `legacy/`，内部复用同一个 `TaskService`，不维护第二套业务实现。

`POST /tasks/current-task` 从未部署到线上，当前代码已删除该路由且不保留 alias。新扩展使用 `POST /tasks/workspace`；旧线上扩展只依赖 `POST /tasks`。

## Context Routing 与资源身份

公开的 Quick Insight / Workspace 请求都不接受客户端 `agent`。`AgentName` 仅是网关内部枚举；`router.py` 根据当前页面上下文选择 Agent：

- LinkedIn / Indeed host 且选中的 JD 至少达到 `MIN_JOB_CONTENT_CHARS`：`job_match`。
- 其他页面或不完整岗位上下文：`summary_page`。

路由后由 Agent 声明 Action：

- `job_match`：`analyze`、`tailor_resume`、`write_cover_letter`、`ask_more`，默认 `analyze`。
- `summary_page`：仅 `ask_more`，默认 `ask_more`。

`normalize_resource_url()` 把原始 URL 转为 Workspace 业务资源标识：

- LinkedIn：`/jobs/view/{job_id}` 或 `currentJobId` 统一为 `https://www.linkedin.com/jobs/view/{job_id}`。
- Indeed：`jk` 或 `vjk` 统一为 `https://{regional-host}/viewjob?jk={job_id}`。
- 普通网页：host 小写，移除 fragment 和全部 `utm_*`，稳定排序其余 query；专用岗位 ID 无法解析时也走此规则。

Quick Insight 返回规范化后的 `resource_url`。Workspace 请求虽携带 `resourceUrl`，服务端仍会从当前 `url` 重新计算并校验，不信任客户端直接指定资源身份。

## 共享历史与文档边界

网关不保存 Workspace Thread；状态保存在扩展当前 Chrome 配置的 `chrome.storage.local`，并在每次请求中完整传回。

- `len(histories) + 1 <= 10`，其中 `1` 是当前用户消息。
- 用户输入和用户历史单条最多 10,000 字符。
- Assistant 历史和 `DocumentContent.text` 最多 100,000 字符。
- `currentDocument` 只接收 `kind`、`title`、`text`，不接受可由服务端重新生成的 HTML / sections。
- 最后一次合法请求会再产生一条 Assistant 消息，因此返回的完整历史可达到 11 条；此后客户端不能继续发送。

本期不做历史截断、摘要、跨设备同步或页面内容版本检测。

## Agent 契约

`agents/base.py` 的 `TaskAgent` 是稳定接口：

```python
class TaskAgent(ABC):
    requires_resume: bool = False

    def validate(self, ctx: AgentContext) -> None: ...
    def actions(self, ctx: AgentContext) -> list[Action]: ...
    def insight(self, ctx: AgentContext) -> AgentExecution[Insight]: ...
    def execute(self, ctx: AgentContext) -> AgentExecution[DocumentContent]: ...
```

`TaskService` 只调用该契约。Quick Insight 的 Actions 直接来自已路由 Agent 的 `actions(ctx)`，不从模型结果推断。简历需求由 `requires_resume` 声明；用户数据只放在请求级 `AgentContext`，Agent 不缓存跨请求、跨用户状态。

## 分层与隐私

- `api.py`：路由、参数、身份解析和 HTTP 错误映射。
- `service.py`：场景编排、Agent 分发、请求级依赖注入、限流和指标落库。
- `repo.py`：`task_records` 持久化。
- `router.py`：Context Router 与资源 URL 归一化纯函数。
- `legacy/`：旧 `/tasks` transport schema 与 adapter。

两个新接口支持 bearer token / session 身份解析、托管模式强制登录和按用户限流。匿名自部署仍可运行；`job_match` 在登录态下注入用户当前生效简历，匿名模式回退 `AGENT_BRIDGE_CV_PATH`。

数据库已配置时，任务记录会持久化运营指标以及可用的 URL、标题、Prompt、页面正文和原始结果。这些明细可能含用户隐私，部署方必须制定数据保留策略。Workspace 历史本身不作为服务端会话保存。

```text
task/
|- api.py
|- schema.py
|- service.py
|- router.py
|- repo.py
|- model.py
|- legacy/
|  |- api.py
|  |- schema.py
|  |- adapter.py
```

PostgreSQL 表结构以 `deploy/initdb/001-schema.sql` 为权威，并与 `model.py` 保持一致。
