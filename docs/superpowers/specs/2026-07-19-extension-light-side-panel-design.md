# Extension Light Side Panel Design

日期：2026-07-19

> [!WARNING]
> 本文是历史视觉方案。Chrome 无法设置 Side Panel 默认宽度、浅色布局与 Action 自动换行
> 约束仍有效；Quick Insight cards、经典聊天时间线、Markdown、Artifact Attachment 与
> CV URL 契约以 [2026-07-19 Job Match Workspace Orchestration Design](2026-07-19-job-match-workspace-orchestration-design.md)
> 为准。

## 1. 目标

将 Chrome Side Panel 从深色工业仪表盘改为简单、清晰的 Chrome 原生浅色工作台，同时修复窄宽度下标题、Actions 和正文横向溢出的问题。Quick Insight 网页浮层继续保持现有深色信息卡，只把 Actions 改成可自动换行的标签按钮。

本次不修改网关接口、Workspace 状态、Action 路由、共享历史或消息上限。

## 2. 平台约束

Chrome `sidePanel` API 不能设置打开时的默认宽度。扩展只能打开面板、选择页面路径以及控制 tab/window 范围，最终宽度由用户控制。因此 Side Panel 必须在 280–600px 的常见宽度内正常工作，不能依赖固定跨度。

验收底线：任何支持宽度下都不得出现页面级横向滚动；标题、来源 URL、Action、历史消息和文档内容都必须收缩或换行。

## 3. 视觉方向

采用 Chrome 原生浅色风格：

- 页面背景：浅灰。
- 内容表面：白色。
- 主文字：深灰；辅助文字：中灰。
- 交互强调：Chrome 蓝，仅用于选中 Action、链接、焦点和发送按钮。
- 边框与阴影保持轻量，不使用大面积黑色、琥珀色、网格背景、信号轨道或工业仪表装饰。
- 字体使用 Chrome/系统 UI 字体，保证扩展页面加载稳定，不引入远程字体。

## 4. Side Panel 信息架构

Side Panel 继续使用四段结构，但压缩无效装饰：

```text
Compact page header
Scrollable context and shared history
Optional latest result
Sticky composer
```

### 4.1 Compact page header

- 删除内部重复的 `Agent Bridge / Workspace` 品牌眉题、信号图形和独立装饰轨道；Chrome 已在面板外层展示扩展名称。
- 岗位或页面标题最多显示两行，超出部分截断。
- 来源链接只显示简短 host/path，并允许自身收缩，不撑开容器。
- 连接状态使用小型中性状态文字，不抢占标题空间。

### 4.2 Quick Insight context

- Quick Insight 作为滚动区顶部的一张紧凑白色卡片。
- 标题与可选匹配分数位于同一视觉层级；不再使用大面积高对比边框。
- Quick Insight 是只读上下文，不进入共享聊天历史。

### 4.3 Shared history

- 无历史时只在 Quick Insight 下方显示一条轻量提示，不再创建全高虚线空状态。
- 用户消息使用浅蓝背景气泡；Agent 消息使用普通白底正文。
- 删除消息序号、工业风竖线和全屏网格；保留清晰的角色区分。
- 所有用户和模型文本使用 `overflow-wrap: anywhere`，代码块在自身内部滚动，不能推动整个 Side Panel 变宽。

### 4.4 Latest result

- `document.kind === "resume"` 时不在 Side Panel 展开完整 CV，也不显示复制全文按钮。
- CV 显示为简洁的网页预览卡：标题、说明和“打开 CV 预览”按钮；按钮在新标签页打开固定测试地址 `https://browser.buildwithyang.com`。
- 固定地址集中定义为一个前端常量，后续网关提供真实 `preview_url` 后可直接替换，不把 URL 散落在 DOM 代码中。
- Cover Letter 等非 CV 文档继续使用白色文本卡片，并保留复制能力；本期不为它们提供网页预览。

### 4.5 Sticky composer

- Composer 固定在底部，使用白色表面和轻边框，不遮挡滚动内容。
- Actions 位于输入框上方，使用内容宽度的圆角标签并通过 `flex-wrap` 自动换行。
- 输入框默认两行，允许纵向扩展；发送按钮放在底部操作行右侧。
- 选中 Action 使用蓝色浅底和蓝色边框；未选中 Action 使用中性灰边框。
- 280–359px 时进一步压缩左右间距和按钮文字尺寸，但不隐藏功能。

## 5. Quick Insight 网页浮层

Quick Insight 主体继续保持当前深色主题，仅调整 Actions：

- Actions 容器从单列改为 `display: flex; flex-wrap: wrap`。
- 每个 Action 使用内容宽度的胶囊标签，不再占满整行。
- 一行能放多少就显示多少，空间不足时自然换行。
- 点击、禁用、错误提示和打开 Shared Workspace 的行为保持不变。

## 6. 组件与代码边界

- `extension/background.js`：只调整 Shadow DOM 内 Quick Insight Action 的结构/样式；请求和 Workspace 打开逻辑不变。
- `extension/sidepanel.html`：删除纯装饰节点，保留语义化 header、timeline 和 composer。
- `extension/sidepanel.css`：实现浅色视觉、响应式布局和无横向溢出约束。
- `extension/sidepanel.js`：保留现有状态模型；将结果渲染拆成 CV 预览与普通文档两条明确分支。
- `extension/README.md`：更新当前用户可见界面说明和 CV 测试预览限制。

## 7. 可访问性与错误处理

- 所有 Action 保留 `aria-pressed`、键盘焦点和 disabled 状态。
- 蓝色焦点环必须在浅色背景上清晰可见。
- CV 预览链接使用 `target="_blank"` 和 `rel="noopener noreferrer"`。
- 固定预览地址仅是当前前端原型行为；链接打开失败不修改 Workspace 或文档状态。
- `prefers-reduced-motion` 下不执行入场动画。

## 8. 测试与验收

- 先增加失败测试，确认 Quick Insight Actions 使用自动换行标签而非强制单列。
- 增加 Side Panel 结构/样式测试，确认浅色主题、可换行 Actions、两行标题和无页面级横向滚动约束。
- 增加渲染测试，确认 CV 使用固定网页预览地址且不走普通文档正文渲染；Cover Letter 仍走普通文本卡片。
- 运行 extension 全部测试和打包测试。
- 在窄宽度与较宽宽度下人工验收：标题、Quick Insight、空历史、四个岗位 Actions、输入框、历史长文本和 CV 预览均不得横向溢出。

## 9. 非目标

- 不尝试通过 Chrome API 设置 Side Panel 默认宽度。
- 不新增或修改 `DocumentContent` / Workspace 网关 schema。
- 不实现真正的 CV 托管、HTML 生成或按用户签名的预览 URL。
- 不把 Side Panel 变成多栏布局，也不增加主题切换。
