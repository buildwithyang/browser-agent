# Agent Bridge - Task Module

Task 模块负责浏览器任务的**请求生命周期**：接收扩展提交的页面上下文 → 分发给对应 agent → （job_match 时）注入登录用户的生效简历 → 执行 → 把**运营指标**落库。

它不是 lsl 的 `job`：`job` 是异步、可持久化、带调度器的后台任务队列（ASR/TTS 这类耗时活）。这里的 task 是**同步交互请求**——扩展点一下、等几秒拿结果，不需要队列与调度器。`agents/`（summary_page / job_match）是被本模块编排的「执行层」。

## 设计原则

- `service.py` 编排：agent 分发、`_resolve_cv_text`（通过 `ResumeService` 取当前用户简历）、执行、落库。
- `router.py` 纯函数路由：LinkedIn、Indeed 都只校验 host；两者都要求选中文本至少 1000 字，再把 `browser_agent` 确定性分流到 `job_match` 或 `summary_page`。
- Agent 标识统一使用 `schema.py` 的 `AgentName(StrEnum)`；Router、Service、Agent 注册表和任务记录不比较裸字符串，HTTP/DB 边界仍使用稳定字符串值。
- `api.py` 只做 HTTP：解析登录态拿 `user_id`（匿名也放行）、调用 service、错误映射（`ValueError`→400，`TaskExecutionError`→502）。
- 持久化 **metrics-only**：`task_records` 表只存 `agent / model / status / input_chars / result_chars / duration_ms / user_id / 时间`。**刻意不存** prompt、结果文本、页面正文、URL——这些是用户隐私（简历、浏览内容）。指标用于用量统计与后续按用户计费 / 限流。
- 持久化可选：无 `DATABASE_URL` 时跳过落库，摘要等能力照常可用。
- `/tasks` 对扩展保持匿名可用：带登录 cookie 时用该用户的生效简历，否则 job_match 回退本地 `AGENT_BRIDGE_CV_PATH`。

## 接口

- `POST /tasks`：执行一次任务，返回 `TaskResponse`（`result` / `result_html` / `sections` / `model` / `duration_ms` / `status`，供扩展面板渲染）。响应不含 prompt。

## 模块结构

```text
task/
|- api.py       # POST /tasks，登录态解析 + 错误映射
|- service.py   # 请求生命周期编排（agent 分发 / 简历注入 / 落库）
|- router.py    # browser_agent 页面上下文的确定性路由（纯函数）
|- repo.py      # task_records 写入与读取（指标）
|- model.py     # ORM 映射（metrics-only）
|- schema.py    # TaskCreate / Section / AgentName / TaskResponse / TaskRecordData
```

建表 SQL 以 `deploy/initdb/001-schema.sql` 的 `task_records` 为权威，与 `model.py` 保持一致。
