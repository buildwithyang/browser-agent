# Agent Bridge - Task Module

Task 模块接收浏览器页面上下文，通过后端 Context Router 选择无状态 Agent，按需注入当前用户简历，执行 Quick Insight 或 Workspace 状态转换，并在数据库已配置时记录运营指标。

## 协议版本

`POST /tasks/quick-insight` 和 `POST /tasks/workspace` 必须携带：

```http
X-Agent-Bridge-Protocol-Version: 2
```

缺失、非法或不等于 `2` 的版本会在身份校验和请求体解析前收到 `426 Upgrade Required`。响应包含当前协议 Header、`Upgrade: Agent-Bridge/2` 和扩展更新地址。成功及接口内部的 `401`、`400`、`429`、`502` 响应同样包含当前协议 Header。

## HTTP 接口

### `POST /tasks/quick-insight`

返回当前页面的 `Insight(title, cards)`、后端声明的 `actions` 和稳定的 Workspace 资源描述，不创建 Artifact。响应 JSON 的 `protocol_version` 固定为 `2`。

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

### `POST /tasks/workspace`

执行一次无状态 Workspace 转换。请求必须携带当前页面、判别式 `trigger`、Action、完整历史和两个固定 Artifact 槽位。

用户消息触发：

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
  "message": "突出我的 Go 项目。"
}
```

Quick Insight Action 触发使用 `"trigger": "quick_insight_action"`，且不允许 `message` 字段。请求不接受客户端指定 `agent`。

响应返回完整的新历史、最新 Artifact 快照和本次结果类型：

```json
{
  "resource_url": "https://www.linkedin.com/jobs/view/4442412976",
  "selected_action_id": "tailor_resume",
  "result_type": "create_artifact",
  "histories": [
    {"role": "user", "content": "突出我的 Go 项目。", "attachments": []},
    {
      "role": "assistant",
      "content": "已生成完整简历。",
      "attachments": [{"type": "cv", "version": 1}]
    }
  ],
  "artifacts": {
    "cv": {"type": "cv", "version": 1, "title": "Tailored CV", "draft": "完整 Markdown"},
    "cover_letter": null
  },
  "meta": {"status": "completed", "model": "configured-model"},
  "protocol_version": 2
}
```

`result_type` 只有 `reply`、`create_artifact`、`update_artifact`。Gateway 把 Markdown 当作不透明文本传输，不解析、不截断、不生成 HTML 或 sections；扩展用响应中的完整 `histories` / `artifacts` 替换本地状态。

### Legacy `POST /tasks`

旧协议已停止执行。精确 `POST /tasks` 不读取请求体、不解析旧 schema、不访问身份或 `TaskService`，始终直接返回相同的 `426` 更新响应。`legacy/api.py` 仅保留 raw `Request` 防御性 fallback。

## Context Routing 与资源身份

公开请求不能选择内部 Agent。`router.py` 根据页面上下文选择：

- LinkedIn / Indeed host 且选中的 JD 达到 `MIN_JOB_CONTENT_CHARS`：`job_match`。
- 其他页面或不完整岗位上下文：`summary_page`。

`normalize_resource_url()` 统一 LinkedIn / Indeed 职位 ID；普通网页会规范 host、移除 fragment 和 `utm_*`、稳定排序 query。Workspace 会从当前 `url` 重新计算并校验 `resourceUrl`。

## 状态与输入边界

- Workspace Thread 由扩展保存在 `chrome.storage.local`，Gateway 不保存会话状态。
- `user_message` 最多携带 9 条历史；`quick_insight_action` 最多携带 10 条。
- 用户文本单条最多 10,000 字符；Assistant 文本和 Artifact draft 最多 100,000 字符。
- `Artifacts` 固定包含 `cv`、`cover_letter` 两个 key；每种类型只携带最新完整快照。
- Gateway 生成消息、Artifact 和 Attachment ID、UTC 时间、版本号，并校验引用一致性。

## Agent 契约

执行层只保留两个显式接口：

```python
class QuickInsightAgent(Protocol):
    def quick_insight(self, context: AgentContext) -> AgentExecution[Insight]: ...
    def available_actions(self, context: AgentContext) -> list[Action]: ...

class WorkspaceAgent(Protocol):
    def handle_chat(self, context: WorkspaceAgentContext) -> AgentExecution[ChatResult]: ...
```

注册到 Gateway 的对象必须同时满足两个接口。Agent 保持无状态，用户简历只存在于请求级 Context。

## 分层与隐私

- `api.py`：路由、参数、身份解析和 HTTP 错误映射。
- `protocol.py`：协议常量、426 工厂和 Router 之前执行的协议 middleware。
- `service.py`：Agent 分发、简历注入、Workspace reducer、限流和指标落库。
- `repo.py`：`task_records` 持久化。
- `router.py`：Context Router 与资源 URL 归一化纯函数。
- `legacy/api.py`：旧入口的 raw 426 fallback。

数据库已配置时只持久化现有任务记录字段；本次协议切换不修改 DB/repository schema。页面正文、Prompt 和结果可能含用户隐私，部署方必须制定数据保留策略。
