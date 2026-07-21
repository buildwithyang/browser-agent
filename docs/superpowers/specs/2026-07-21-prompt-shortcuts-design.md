# Prompt Shortcuts 与十轮 Workspace 设计

日期：2026-07-21  
状态：已确认，待实施

## 1. 目标与决策

Workspace 不再把 Action 当作 Agent 路由参数。Quick Insight 和 Side Panel 中原有的
Action 改为 Prompt Shortcut：点击只打开 Workspace、把服务端声明的 Prompt 填入输入框
并聚焦，不自动发送。用户可以编辑后再提交；后端只根据当前消息、完整历史、Artifact、
JD 和 CV 判断意图。

本期采用 **Protocol v4 干净切换**：不保留 v3 Workspace Action 请求兼容层。旧扩展访问
v4 Gateway 时收到 `426 Upgrade Required`。Workspace 上限改为真正的十轮，即最多十次
用户发送及其对应的十次 Assistant 回复。

## 2. Protocol v4 公共契约

### Quick Insight

Gateway 根据页面类型和请求中的输出语言返回本地化 Prompt Shortcuts：

```json
{
  "insight": {"title": "Worth Applying", "cards": []},
  "shortcuts": [
    {
      "id": "analyze",
      "title": "分析岗位",
      "prompt": "请分析这个岗位真正看重的能力、我的匹配优势、核心差距，以及是否值得申请。请给出明确结论和理由。"
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
  "protocol_version": 4
}
```

`PromptShortcut` 使用严格字段 `id`、`title`、`prompt`；`prompt` 允许空字符串。LinkedIn /
Indeed 返回四个 Shortcut，普通网页只返回 `ask_more`。`lang=zh` 使用上述中文，`lang=en`
使用语义一致的英文文案：

- Analyze: `Analyze what this role actually values, my strongest matches, the most important gaps, and whether it is worth applying. Give a clear recommendation with reasons.`
- Tailor Resume: `Compare the current job description with my resume. First identify the experiences worth emphasizing and the sections you plan to change. Do not generate a new resume yet; wait for my confirmation.`
- Cover Letter: `Using the current job description and my resume, write a concise, specific cover letter without exaggeration. Emphasize only the experience most relevant to the role.`
- Ask More: empty string.

Quick Insight response 删除 `actions`，`WorkspaceDescriptor` 删除 `default_action_id`。

### Workspace

`POST /tasks/workspace` 只接受用户消息，不再存在 Quick Insight Action 执行分支：

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

请求删除 `trigger` 和 `actionId`。`HistoryMessage` 删除 `action_id`；终态
`WorkspaceResponse` 删除 `selected_action_id`。NDJSON 事件顺序、流式 reply、Artifact
status-only 和原子 completed commit 保持不变，所有 Header/body 协议版本改为 `4`。

## 3. Agent 与 Extension 行为

### Agent 编排

`JobChatContext` 只包含 request、resume、histories、artifacts 和必填 current message，不再
包含 trigger 或 selected Action。`JobMatchAgent` 删除 Quick Action 确定性计划；每次
Workspace 请求都经过 `ChatPlanner`，优先级为：

```text
current message > current Artifacts > histories
```

Tailor Resume Shortcut 的首条 Prompt 明确要求只给修改计划，因此返回普通 reply；用户后续
确认生成时，Planner 根据确认消息和历史进入 CV Artifact 模式。Cover Letter Shortcut 的
Prompt 明确要求生成完整求职信，因此进入 Cover Letter Artifact 模式。模型仍负责最终
`reply | create_artifact | update_artifact` 判断。

### Shortcut 交互

- Quick Insight 点击 Shortcut：先 seed/open 同一资源 Workspace，再填充输入框；不调用
  `/tasks/workspace`。
- Side Panel 点击 Shortcut：用该 Prompt 替换输入框现有内容并聚焦；不改变历史或 Artifact。
- Ask More：清空输入框并聚焦。
- Shortcut 只是可编辑草稿；发送时只提交最终输入文本，不提交 Shortcut id。
- 达到十轮时忽略 prefill，Shortcut 与发送按钮保持禁用。

Gateway 继续决定不同页面可用的 Shortcut 及其 Prompt，因此以后调整文案或页面能力不需要
重新发布扩展；协议字段结构变化才需要发布。

## 4. 十轮限制与本地迁移

轮数只统计 canonical history 中 `role=user` 的消息：

- 少于 10 条 User Message 时允许发送；第 10 条允许提交。
- 第 10 轮 pending 时计数器立即显示 `10 / 10`；失败后恢复为 `9 / 10`。
- 第 10 轮成功后最多保存 20 条 history，输入框和 Shortcut 禁用。
- 禁用输入框的 placeholder 显示 `当前最多支持10轮聊天`；英文显示
  `This Workspace supports up to 10 turns.`；键盘操作提示隐藏。
- 失败、取消、断流或非法响应不提交 canonical history，因此不消耗轮数。
- Gateway 以 User Message 数量执行同一限制，不能仅依赖 Extension。

Extension 本地 Workspace schema 从 v2 升到 v3，状态保存
`resourceUrl/pageTitle/quickInsight/shortcuts/histories/artifacts/updatedAt`，删除
`actions/selectedActionId`。提供一次 v2 → v3 迁移：保留 history、Artifact 和页面元数据，
删除每条 history 的 `action_id`，丢弃旧 Action 选择，并用下一次 Quick Insight seed 更新
Shortcuts。只保证 v2 迁移；更早的 v1 legacy migration 删除。

## 5. 验收、发布与文档

自动化测试必须覆盖：

- Protocol v4 严格拒绝 `trigger`、`actionId`、`selected_action_id` 和 history
  `action_id`，v3 Header 返回 426。
- Quick Insight 按页面和 zh/en 返回完整 Shortcuts；普通页面只有空 Prompt 的 Ask More。
- 两个 UI 入口都只 prefill、不发送；Shortcut 替换现有输入，Ask More 清空输入。
- 发送请求只携带最终 message；Planner 能完成 Analyze、先计划后生成 CV、直接生成或更新
  Cover Letter、开放追问四条路径。
- 第 10 个用户消息允许成功，第 11 个被前后端拒绝；pending、失败恢复、计数器、禁用状态和
  中英文上限提示正确。
- v2 Workspace 可迁移到 v3，历史和 Artifact 不丢失且所有 Action 字段被移除。
- Gateway 全量测试、Extension 全量测试、生产 ZIP 和 import check 通过。

这是协调发布：Gateway 升级到 v4 后，旧扩展立即收到更新提示；随后发布 Extension
`0.3.0`。不提供 v3/v4 双协议窗口。同步更新用户 README、Task/Job Match 模块 README、
共享 Workspace 与 streaming 设计文档中的旧 Action 和十条消息描述。

