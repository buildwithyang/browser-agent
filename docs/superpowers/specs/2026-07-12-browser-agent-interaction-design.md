# Browser Agent Interaction Design

日期：2026-07-12

## 1. 目标

Browser Agent 不从聊天框开始，而是先在用户当前关注的页面上给出 **Quick Insight**，回答：

> 我现在最应该知道什么？

用户完成初步判断后，再通过明确的 Action 进入 Side Panel Workspace 完成任务，并在同一任务上下文中继续修改结果。

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
Workspace (Side Panel)
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
- 其他网站回退到通用页面 Summary，Action 仅为 `Ask more`。
- Quick Insight 仍在当前网页的轻量浮层中展示。
- Action 打开持久 Side Panel Workspace。
- Follow-up MVP 使用客户端回传 `prior_result`，不引入服务端 Thread。
- Popup 只保留输出语言，不向普通用户暴露 Gateway URL。

以下能力属于后续阶段，不在第一轮实现中完成：

- 完整 Tailor Resume 工作流。
- Mock Interview 工作流。
- 跨设备历史任务恢复。
- 服务端 Workspace / Thread 持久化。
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

后端根据页面 URL、标题、用户选中文本和可见内容判断页面类型，并返回对应的 Quick Insight schema。

第一阶段路由：

```text
LinkedIn / Indeed job page → job_match
other page                → summary_page
```

岗位判断不应只依赖域名。LinkedIn / Indeed 的非岗位页面也应回退到通用 Summary；只有页面内容满足岗位资料要求时才进入 `job_match`。

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

Actions
  Deep Analysis
  Tailor Resume
  Write Cover Letter
  Mock Interview
```

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

Actions
  Ask more
```

通用页面不展示岗位分数，也不展示不可用的求职 Actions。

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
  "label": "Write Cover Letter",
  "workspace_type": "cover_letter",
  "enabled": true
}
```

第一阶段可真正执行：

- `Deep Analysis`
- `Write Cover Letter`
- 通用页面的 `Ask more`

第一阶段可作为后续入口预留但不得伪装成已完成功能：

- `Tailor Resume`
- `Mock Interview`

若按钮尚未实现，应隐藏或明确标注为即将推出；默认选择隐藏，避免无效操作。

## 7. Layer 2 — Workspace (Side Panel)

### 7.1 定位

Side Panel 是持久工作台，不是通用聊天首页。每次由一个明确 Action 打开，并带着该任务的专用结构进入。

```text
Quick Insight
  ↓ Action
Side Panel Workspace
```

### 7.2 固定结构

Side Panel 使用现有 Agent Bridge 视觉语言，不照搬普通翻译扩展的浅色卡片堆叠：

1. 顶部固定岗位/页面身份条：标题、公司或站点、来源链接。
2. 当前任务标题：Deep Analysis、Cover Letter 或 Ask more。
3. 主结果区：当前最新产物。
4. 必要的复制、版本或重新生成操作。
5. 底部固定 Follow-up 输入框。

工作区内容可以滚动，顶部身份条和底部输入框保持可见。

### 7.3 Workspace 类型

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
+ user instruction
→ next result
```

客户端 Side Panel 保存当前任务的累积上下文，并在下一轮请求中回传 `prior_result`。后端继续注入当前登录用户的生效 CV，不从客户端接受或信任其他用户的 CV 数据。

### 8.2 `prior_result` 能力边界

`prior_result` 足以实现第一版多轮 Follow-up，但需要明确限制：

- 当前最大长度为 50,000 字符。
- 每轮重复传输历史，Token 与网络成本会随轮次增长。
- Side Panel 被清空、扩展重载或更换设备后，未持久化历史无法自动恢复。
- 客户端回传内容只能作为用户输入，不能作为授权依据或可信服务端状态。

达到长度阈值前，客户端应保留：

- 页面摘要或 JD 关键事实。
- 当前最新产物。
- 最近若干轮用户要求与结果。
- 更早轮次的压缩摘要。

只有出现跨设备恢复、任务历史列表、长期版本管理等真实需求时，才升级到服务端 `workspace_id` / Thread。

## 9. 组件边界

### 扩展 Popup

- 只管理输出语言。
- 不处理网关配置。

### Background Service Worker

- 采集并发送统一 Browser Agent 请求。
- 打开 Quick Insight。
- 根据 Action 打开 Side Panel 并传递初始上下文。
- 不实现业务路由规则。

### Quick Insight Renderer

- 根据后端返回的 `insight_type` 和结构化字段渲染。
- 负责短结果与 Action，不承载多轮输入。

### Side Panel

- 按 `workspace_type` 渲染任务工作区。
- 管理当前任务的 `prior_result` 和 Follow-up 请求。
- 不直接访问其他模块的用户数据。

### Gateway Router

- 判断页面上下文并选择 Agent。
- 无法判断时回退 Summary。

### Agent

- 生成对应 Quick Insight / Workspace 内容。
- 不缓存跨请求、跨用户状态。

## 10. 测试与验收

### Popup

- 不再显示或读写 Gateway URL。
- 语言偏好行为保持不变。
- 生产构建使用云端地址，本地开发使用 `127.0.0.1:17321`。

### Routing

- 完整 LinkedIn / Indeed JD 路由到 `job_match`。
- LinkedIn / Indeed 非岗位页回退 `summary_page`。
- 普通网页返回 Summary + Ask more。
- 不确定或异常路由安全回退 Summary。

### Quick Insight

- 匹配分以独立数字展示。
- 申请建议与一句核心判断清晰可见。
- 行业业务与岗位职责合并为岗位概览，但内部标签清楚。
- 首屏只展示最大优势与最大差距。
- Action 由后端声明，扩展不写死业务按钮。

### Workspace

- Action 能打开正确的 Side Panel Workspace。
- Workspace 始终保留页面/岗位身份。
- Cover Letter 与 Ask more 能使用 `prior_result` 连续完成至少三轮修改。
- 刷新或请求失败不会误把其他任务的上下文带入当前任务。
- 401、网络错误和超过长度限制都有明确恢复方式。

## 11. 实施阶段

为避免一次改动跨越过多子系统，实施拆成三个连续里程碑，每个里程碑单独计划与验收：

### Milestone 1 — Quick Insight Foundation

- Popup 移除 Gateway URL。
- 单一 Browser Agent 右键入口。
- 后端 Context Routing。
- LinkedIn / Indeed 决策卡。
- 通用 Summary + Ask more。

### Milestone 2 — Side Panel Workspace

- Side Panel 容器和任务身份条。
- Deep Analysis Workspace。
- Cover Letter Workspace。
- 通用 Ask more Workspace。

### Milestone 3 — Follow-up

- `prior_result` 多轮请求。
- 历史压缩策略。
- 当前产物替换/版本交互。
- 长度、刷新和错误恢复。

后续 Tailor Resume、Mock Interview 与服务端持久化分别进入独立设计与实施周期。
