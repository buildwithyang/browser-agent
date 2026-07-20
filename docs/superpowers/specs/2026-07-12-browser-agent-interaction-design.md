# Browser Agent Interaction Design

日期：2026-07-12

> [!WARNING]
> 本文是历史设计。Decision First、Context Routing 与 Quick Insight 原则仍有效；
> Current Task、`DocumentContent`、`prior_result`、Actions 和 Follow-up wire contract 已由
> [2026-07-19 Job Match Workspace Orchestration Design](2026-07-19-job-match-workspace-orchestration-design.md)
> 替代。当前接口是 `/tasks/quick-insight` + `/tasks/workspace` 协议版本 2。

## 1. 目标

Browser Agent 不从聊天框开始，而是先在用户当前关注的页面上给出 **Quick Insight**，回答：

> 我现在最应该知道什么？

用户完成初步判断后，再通过明确的 Action 进入 Side Panel Current Task 完成任务，并在同一任务上下文中继续修改结果。

统一流程：

```text
Right Click
  ↓
Browser Agent
  ↓
Context Routing
  ↓
Quick Insight
  ↓
Actions
  ↓
Current Task (Side Panel)
  ↓
Follow-up
```

设计原则：

- **Decision First**：先帮助用户判断，再让用户投入更多注意力。
- **Action Oriented**：优先回答“下一步最值得做什么”，而不是先问“你想聊什么”。
- **Context Persistent**：当前网页、当前任务和前序结果贯穿整个工作流。
- **Attention First**：只处理用户明确选择的页面，不持续监控浏览行为。

## 2. 本期范围与产品边界

本期建立统一交互骨架，优先跑通招聘岗位页面：

- 右键菜单统一为一个 `Browser Agent` 入口。
- LinkedIn / Indeed 使用岗位专用 Quick Insight。
- 其他网站回退到通用页面 Summary；Milestone 2 启用后，Action 仅为 `Ask more`。
- Milestone 1 在当前网页的轻量浮层中展示 Quick Insight，并隐藏所有不可执行 Action。
- Milestone 2 启用相关 Action，并打开持久 Side Panel Current Task。
- Milestone 3 的 Follow-up MVP 使用客户端回传当前产物与 `histories`，不引入服务端 Thread。
- Popup 只保留输出语言，不向普通用户暴露 Gateway URL。

以下能力属于后续阶段，不在第一轮实现中完成：

- 完整 Tailor Resume 工作流。
- Mock Interview 工作流。
- 跨设备历史任务恢复。
- 服务端 Current Task / Thread 持久化。
- GitHub、Jira、Gmail、ChatGPT、Claude、Notion 的专用 Agent。

## 3. Popup 设置简化

### 3.1 用户界面

Popup 只承担输出语言选择：

- 跟随浏览器。
- 中文。
- English。
- 跟随页面。

删除 Gateway URL 标题、输入框和提示文案。普通用户无需理解网关概念。

### 3.2 环境配置

- Chrome 商店生产包固定使用 `https://browser.buildwithyang.com/api`。
- 本地开发固定使用 `http://127.0.0.1:17321`。
- 生产与本地通过构建配置区分，不能依赖开发者每次手改源码。
- 请求、鉴权、401 登录跳转继续从同一个配置模块读取网关地址。

普通用户不再通过 Popup 连接私有部署。若未来恢复自部署支持，应单独设计开发者模式，而不是重新暴露一级输入框。

## 4. Context Routing

### 4.1 单一入口

扩展不再暴露“总结此页面”“分析与简历匹配”等多个 Agent 菜单项：

```text
Right Click → Browser Agent
```

扩展只负责采集用户明确选择的页面上下文并发起统一请求，不负责决定具体 Agent。

### 4.2 后端路由

后端根据页面 host、URL 和用户选中文本判断页面类型，并返回对应的 Quick Insight schema。

第一阶段路由：

```text
LinkedIn / Indeed host + 完整 JD → job_match
other host / 不足 1000 字选区    → summary_page
```

LinkedIn、Indeed 都可能因 SPA 或地区站点使用不同的职位路径，因此两者的 URL 条件都只校验主域名或其子域名。为避免无关页面误匹配，仍要求用户明确选中至少 1000 个字符的完整 JD。

路由失败或无法判断时不得报错，必须安全回退到 `summary_page`。

## 5. Layer 1 — Quick Insight

### 5.1 通用结构

Quick Insight 是当前页面上的轻量决策浮层，不是聊天窗口：

```text
Quick Insight
  ↓
Actions
```

浮层应在几秒内让用户看懂结果，并保持现有 Agent Bridge 深色工业仪表风格与黄色信号色。

### 5.2 LinkedIn / Indeed 岗位页面

岗位 Quick Insight 采用“决策卡”结构：

```text
87 / 100
值得申请

核心技术要求基本命中，仅缺少直接行业经验。

岗位概览
  行业与业务
  岗位核心
  1-2 句职责摘要

最大优势
最大差距
```

Milestone 1 只展示上述决策卡，不显示尚不可执行的 Actions。Milestone 2 再启用
`Summary`、`Deep Analysis` 和 `Write Cover Letter`，并打开对应的 Side Panel Current Task。
`Tailor Resume` 与 `Mock Interview` 继续隐藏，留待后续独立里程碑。

#### 匹配分

匹配分必须是独立结构化字段，不能继续融合在一整段结论文字中。

建议字段：

```text
score: 0..100
recommendation: strong_apply | apply | cautious | skip
reason: 一句核心判断
```

前端分别渲染数字、申请建议和理由，避免从 HTML 文本中用正则提取分数。

#### 岗位概览

原“公司业务和行业背景”与“岗位描述”合并成一个 `job_overview` 区块，但区块内部保留清晰标签：

- `industry_business`：公司产品、行业、市场与业务模式。
- `role_focus`：岗位最核心的责任。
- `summary`：1-2 句职责摘要。

合并的目的是减少重复卡片，不是把所有内容重新写成长段文字。

#### 优势与差距

Quick Insight 只展示最重要的一项优势和一项差距。完整技能逐项匹配进入 `Deep Analysis`，避免首屏过长。

### 5.3 其他网站

未命中专用 Agent 的页面统一返回：

```text
Page Summary

2-4 句当前页面摘要
```

Milestone 1 的通用页面不展示岗位分数或任何不可用 Action。Milestone 2 再启用
`Ask more`，并打开通用页面的 Side Panel Current Task。

### 5.4 错误状态

- 页面内容不足：明确说明需要选中或打开完整内容，并保留当前页面。
- 网关不可用：生产环境只显示连接失败和重试，不暴露网关地址。
- 401：保持现有登录跳转与自动重连流程。
- 路由不确定：回退通用 Summary，不让用户处理路由错误。

## 6. Actions

Actions 由后端随 Quick Insight 返回，扩展只按 schema 渲染，不在扩展中写死各 Agent 的按钮。

建议契约：

```json
{
  "id": "write_cover_letter",
  "title": "Write Cover Letter"
}
```

Milestone 1 尚未实现 Side Panel，因此所有不可执行 Action 均隐藏，不展示死按钮。

Milestone 2 可真正执行：

- LinkedIn / Indeed 岗位页面的 `Summary`
- `Deep Analysis`
- `Write Cover Letter`
- 通用页面的 `Ask more`

以下能力继续作为后续入口预留，但不得伪装成已完成功能：

- `Tailor Resume`
- `Mock Interview`

若按钮尚未实现，应隐藏或明确标注为即将推出；默认选择隐藏，避免无效操作。

### 6.1 场景 API 边界

不同交互层使用不同 URL 和确定的响应类型：

```text
POST /tasks/quick-insight
  → QuickInsightResponse { request, insight, actions, meta }

POST /tasks/current-task
  → TaskResponse { request, document, meta }
```

`Insight` 使用 `title + cards` 的通用结构；`DocumentContent` 使用 `text + html + sections`。Quick Insight 响应不存在 `sections`，Current Task 响应不存在 `insight`，客户端无需判断联合响应。

旧 `POST /tasks` 仅作为 Chrome 扩展审核迁移期的 deprecated 兼容入口。旧 schema 与 adapter 隔离在 `modules/task/legacy/`，只转换协议并调用新 Service，不复制 Agent 或业务逻辑。

## 7. Layer 2 — Current Task (Side Panel)

### 7.1 定位

Side Panel 展示用户当前正在完成的任务，不是通用聊天首页。每次由一个明确 Action 打开，并带着该任务的专用结构进入。

```text
Quick Insight
  ↓ Action
Side Panel Current Task
```

### 7.2 固定结构

Side Panel 使用现有 Agent Bridge 视觉语言，不照搬普通翻译扩展的浅色卡片堆叠：

1. 顶部固定岗位/页面身份条：标题、公司或站点、来源链接。
2. 当前任务标题：Summary、Deep Analysis、Cover Letter 或 Ask more。
3. 主结果区：当前最新产物。
4. 必要的复制、版本或重新生成操作。
5. 底部固定 Follow-up 输入框。

工作区内容可以滚动，顶部身份条和底部输入框保持可见。

### 7.3 Current Task 类型

#### Summary

- 显示当前 LinkedIn / Indeed 岗位的精简摘要。
- 保留岗位、公司和来源页面上下文，便于继续追问。

#### Deep Analysis

- 完整岗位概览。
- 逐项技能匹配。
- 评分依据。
- 简历改进方向。

#### Cover Letter

- 可复制的最新 Cover Letter。
- Follow-up 示例：“缩短到 180 字”“突出 Kubernetes”“重写开头”。
- 每轮替换或形成一个新版本，不能把所有版本堆成不可读的聊天气泡。

#### Ask more

- 显示当前页面 Summary。
- 接受用户自由问题。
- 回答始终基于当前页面与当前任务历史。

## 8. Layer 3 — Follow-up

### 8.1 MVP 数据流

MVP 保持 Agent 无状态：

```text
current page context
+ current task type
+ prior_result
+ histories
+ current message
→ next result
```

客户端 Side Panel 保存 Current Task 的最新产物和消息历史，并在下一轮请求中回传：

- `prior_result`：当前最新产物，例如正在修改的 Cover Letter。
- `histories`：此前的用户消息与 Agent 回复，按发生顺序排列。
- `message`：用户当前发送的消息。

后端继续注入当前登录用户的生效 CV，不从客户端接受或信任其他用户的 CV 数据。

### 8.2 Follow-up 轮数限制

MVP 用消息条数控制 Current Task 的长度：

- `histories` 中每一条用户消息或 Agent 回复各计 1 条。
- 当前待发送的 `message` 计 1 条。
- `len(histories) + 1` 不得超过 10。
- 因此一次请求最多携带 9 条历史消息和 1 条当前消息。
- 后端必须再次校验该限制，不能只依赖扩展端校验。
- 达到上限后，Side Panel 保留当前产物，禁用继续发送，并提示用户开启一个新的 Current Task。
- 不静默删除历史，也不在本期自动压缩历史，避免模型在用户不知情时丢失约束。

`prior_result` 仍需保留自身的请求长度上限；它不计入 10 条消息，但会计入模型 Token 成本。

此方案足以实现第一版多轮 Follow-up，但仍有以下边界：

- 每轮重复传输历史与当前产物，Token 和网络成本会随轮次增长。
- Side Panel 被清空、扩展重载或更换设备后，未持久化历史无法自动恢复。
- 客户端回传内容只能作为用户输入，不能作为授权依据或可信服务端状态。

只有出现跨设备恢复、任务历史列表或长期版本管理等真实需求时，才升级到服务端 `task_id` / Thread。

## 9. 组件边界

### 扩展 Popup

- 只管理输出语言。
- 不处理网关配置。

### Background Service Worker

- 采集并发送统一 Browser Agent 请求。
- 打开 Quick Insight。
- Milestone 2 根据已启用 Action 打开 Side Panel 并传递初始上下文。
- 不实现业务路由规则。

### Quick Insight Renderer

- 根据后端返回的 `Insight(title, cards)` 渲染不同卡片类型。
- 负责短结果与 Action，不承载多轮输入。

### Side Panel

- 按 `task_type` 渲染 Current Task。
- 管理当前任务的 `prior_result`、`histories` 和 Follow-up 请求。
- 不直接访问其他模块的用户数据。

### Gateway Router

- 判断页面上下文并选择 Agent。
- 无法判断时回退 Summary。
- 网关内部使用中央 `AgentName(StrEnum)` 表示 Agent 标识；Router、Service、Agent 注册表与任务记录禁止依赖裸字符串比较。
- HTTP JSON 与数据库仍使用 `browser_agent`、`job_match`、`summary_page` 等稳定字符串值，保持扩展和既有数据兼容。

### Agent

- 生成对应 Quick Insight / Current Task 内容。
- 不缓存跨请求、跨用户状态。
- 实现统一 `TaskAgent` 契约：`validate(ctx)`、`insight(ctx)`、`execute(ctx)`。
- 通过请求级 `AgentContext` 接收简历等用户数据；Service 不探测可选方法，也不判断具体 Agent 类型。

## 10. 测试与验收

### Popup

- 不再显示或读写 Gateway URL。
- 语言偏好行为保持不变。
- 生产构建使用云端地址，本地开发使用 `127.0.0.1:17321`。

### Routing

- 任意 LinkedIn / Indeed 页面选中至少 1000 字时路由到 `job_match`。
- LinkedIn / Indeed 短选区和其他 host 回退 `summary_page`。
- Router 返回 `AgentName` 枚举，Service 使用枚举成员判断；API JSON 仍序列化为原有字符串值。
- 普通网页在 Milestone 1 返回 Summary；Milestone 2 再提供 `Ask more`。
- 不确定或异常路由安全回退 Summary。

### Quick Insight

- 匹配分以独立数字展示。
- 申请建议与一句核心判断清晰可见。
- 行业业务与岗位职责合并为岗位概览，但内部标签清楚。
- 首屏只展示最大优势与最大差距。
- Milestone 1 隐藏所有尚不可执行的 Action，不出现死按钮。
- Milestone 2 的 Action 由后端声明，扩展不写死业务按钮。
- Milestone 2 的 LinkedIn / Indeed Actions 包含 `Summary`。

### Current Task（Milestone 2）

- Action 能打开正确的 Side Panel Current Task。
- Current Task 始终保留页面/岗位身份。

### Follow-up（Milestone 3）

- Cover Letter 与 Ask more 能使用 `prior_result + histories + message` 连续修改。
- `len(histories) + 1 <= 10` 时允许发送；超过限制时扩展端和后端都拒绝。
- 达到 10 条后保留当前产物，并明确引导用户开启新的 Current Task。
- 刷新或请求失败不会误把其他任务的上下文带入当前任务。
- 401、网络错误和消息条数超限都有明确恢复方式。

## 11. 实施阶段

为避免一次改动跨越过多子系统，实施拆成三个连续里程碑，每个里程碑单独计划与验收：

### Milestone 1 — Quick Insight Foundation

- Popup 移除 Gateway URL。
- 单一 Browser Agent 右键入口。
- 后端 Context Routing。
- LinkedIn / Indeed 决策卡。
- 通用 Summary。
- 隐藏所有尚不可执行的 Actions。

### Milestone 2 — Side Panel Current Task

- Side Panel 容器和任务身份条。
- 启用岗位页面的 `Summary`、`Deep Analysis`、`Write Cover Letter` 和通用页面的 `Ask more` Actions。
- Summary Current Task。
- Deep Analysis Current Task。
- Cover Letter Current Task。
- 通用 Ask more Current Task。

### Milestone 3 — Follow-up

- `prior_result + histories + message` 多轮请求。
- 10 条消息的前后端限制。
- 当前产物替换/版本交互。
- 消息超限、刷新和错误恢复。

后续 Tailor Resume、Mock Interview 与服务端持久化分别进入独立设计与实施周期。
