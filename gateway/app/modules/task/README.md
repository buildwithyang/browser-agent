# Agent Bridge - Task Module

Task 模块负责浏览器任务的同步请求生命周期：接收页面上下文、路由到对应 Agent、注入请求级用户简历、执行并在数据库已配置时持久化任务记录。

## 场景接口

- `POST /tasks/quick-insight`：返回 `QuickInsightResponse`，包含 `Insight(title, cards)`、`actions` 和稳定的 `workspace` 描述，不返回文档区块。
- `POST /tasks/workspace`：接收当前页面、Action、共享历史和最新草稿，返回完整新历史与最新 `DocumentContent`；服务端不保存 Workspace 会话。
- `POST /tasks`：deprecated 旧扩展兼容入口；协议类型和转换集中在 `legacy/`，内部仍调用新 `TaskService`，没有第二套业务实现。

两个新接口都不接受客户端指定 `agent`，由网关按页面上下文路由；它们支持 bearer token / session 身份解析、托管模式强制登录、按用户限流和任务记录持久化。匿名自部署仍可运行；`job_match` 在登录态下注入用户当前生效简历，匿名模式回退 `AGENT_BRIDGE_CV_PATH`。

Quick Insight 返回的 `resource_url` 是 Workspace 业务资源标识。LinkedIn 和 Indeed 职位 URL 会按岗位 ID 归一；普通 URL 会移除 fragment 和全部 `utm_*` 参数，并稳定排序其余 query。`POST /tasks/workspace` 会根据当前 `url` 重新计算并校验该标识，不信任客户端直接传入的 `resourceUrl`。

`currentDocument` 只接收有界的 `kind`、`title`、`text` 源字段，不接收可由服务端重新生成的 HTML 或 sections。用户输入和用户历史单条最多 10,000 字符；Agent 文档正文及对应 Assistant 历史单条最多 100,000 字符。

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

`TaskService` 只调用该契约；Quick Insight 的 Actions 通过已路由 Agent 的 `actions(ctx)` 获取，不从模型执行结果推断。简历需求由 `requires_resume` 声明，用户数据只放在请求级 `AgentContext`，Agent 不缓存跨用户状态。

## 分层与隐私

- `api.py`：参数、身份解析和 HTTP 错误映射。
- `service.py`：场景编排、Agent 分发、请求级依赖注入、限流和指标落库。
- `repo.py`：`task_records` 持久化。
- `router.py`：Context Router 与 URL 归一化纯函数；LinkedIn / Indeed 只匹配 host，并要求至少 1000 字选中 JD。
- `legacy/`：旧 `/tasks` transport schema 与 adapter，只做协议转换。

数据库已配置时，任务记录会持久化指标以及可用的 URL、标题、Prompt、页面正文和原始结果。明细可能包含用户隐私，部署方应据此制定数据保留策略；无数据库时任务保持无状态运行。

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
