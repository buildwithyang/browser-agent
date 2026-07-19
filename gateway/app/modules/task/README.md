# Agent Bridge - Task Module

Task 模块负责浏览器任务的同步请求生命周期：接收页面上下文、路由到对应 Agent、注入请求级用户简历、执行并在数据库已配置时持久化任务记录。

## 场景接口

- `POST /tasks/quick-insight`：返回 `QuickInsightResponse`，只包含 `Insight(title, cards)` 和 `actions`，不返回文档区块。
- `POST /tasks/current-task`：返回 `TaskResponse`，只包含 `DocumentContent(text, html, sections)`。
- `POST /tasks`：deprecated 旧扩展兼容入口；协议类型和转换集中在 `legacy/`，内部仍调用新 `TaskService`，没有第二套业务实现。

两个新接口都支持 bearer token / session 身份解析、托管模式强制登录、按用户限流和任务记录持久化。匿名自部署仍可运行；`job_match` 在登录态下注入用户当前生效简历，匿名模式回退 `AGENT_BRIDGE_CV_PATH`。

## Agent 契约

`agents/base.py` 的 `TaskAgent` 是稳定接口：

```python
class TaskAgent(ABC):
    requires_resume: bool = False

    def validate(ctx: AgentContext) -> None: ...
    def insight(ctx: AgentContext) -> AgentExecution[Insight]: ...
    def execute(ctx: AgentContext) -> AgentExecution[DocumentContent]: ...
```

`TaskService` 只调用该契约，简历需求由 `requires_resume` 声明，用户数据只放在请求级 `AgentContext`，Agent 不缓存跨用户状态。

## 分层与隐私

- `api.py`：参数、身份解析和 HTTP 错误映射。
- `service.py`：场景编排、Agent 分发、请求级依赖注入、限流和指标落库。
- `repo.py`：`task_records` 持久化。
- `router.py`：Context Router 纯函数；LinkedIn / Indeed 只匹配 host，并要求至少 1000 字选中 JD。
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
