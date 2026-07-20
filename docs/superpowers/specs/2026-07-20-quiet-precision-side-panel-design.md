# Agent Bridge Quiet Precision Side Panel Design

日期：2026-07-20

状态：已确认设计，待实施。

> [!NOTE]
> 本文替代 [2026-07-19 Extension Light Side Panel Design](2026-07-19-extension-light-side-panel-design.md)
> 中所有 Side Panel 视觉和布局，包括其 Quick Insight context card 与 standalone latest
> result；旧文档中 Chrome 无法设置默认宽度、280–600px 响应式、无横向溢出
> 和网页 Quick Insight 浮层 Action 自动换行约束仍然有效。

## 1. 背景

当前 Side Panel 已经具备共享时间线、Action、Markdown、Artifact、错误恢复和
10 条消息限制，但视觉上存在三个问题：

- 暖灰和琥珀色与 Agent Bridge 紫色图标割裂，整体显得陈旧。
- Header、Message、Attachment 和 Composer 多层边框叠加，视觉噪音过高。
- 空 Workspace 只有一行文字，下方形成大面积无意义留白；Composer 更像表单，
  不像一个聊天工具。

本次重设计采用已确认的 **Quiet Precision / 安静精密** 方向：冷静浅色底、
白色内容面、单一品牌紫点缀和明确的任务层级。

## 2. 目标与非目标

### 目标

- 让 Side Panel 看起来像现代 AI 工作台，而不是一组嵌套卡片。
- 在 280–600px 常见宽度保持清晰层级，不产生整页横向滚动。
- 突出聊天内容和输入动作，降低边框、标签与装饰的存在感。
- 保留现有 Workspace 功能、可访问性与状态安全边界。

### 非目标

- 不修改 Gateway API、protocol v2、Workspace schema 或本地持久化。
- 不在 Side Panel 中渲染 Quick Insight、Business Overview、Strength 或 Gap 卡片；
  Quick Insight 仍只在网页浮层中展示。
- 不在时间线外渲染 standalone latest Artifact；Attachment 仍属于生成它的
  Assistant Message。
- 不增加导航栏、多 Workspace 列表、主题切换或新的品牌动画。
- 不尝试设置 Chrome Side Panel 的默认宽度；Chrome 没有对应 API。

## 3. 视觉系统

### 3.1 颜色

```text
Canvas          #F7F8FB
Surface         #FFFFFF
Surface subtle  #FAFBFC
Ink             #1B1C25
Ink muted       #70727D
Line            #E8E9EE
Brand           #604BD8
Brand soft      #F0EDFF
Danger          #B5483F
Danger soft     #FFF1EF
```

紫色只用于选中 Action、输入聚焦、发送按钮、匹配分数和可操作元素。不使用
大面积紫色背景、紫色渐变或多个竞争性强调色。

`Ink muted` 对白色和 Canvas 的对比度分别约为 4.78:1 和 4.50:1；`Brand` 对
`Brand soft` 约为 5.22:1。辅助文字和选中 Action 因此不依赖大字号例外才能
满足 WCAG AA。

### 3.2 字体

- 在 Extension 内置一份可商用的 `DM Sans` Latin WOFF2，不从 CDN 加载。
- 中文使用 `PingFang SC`, `Microsoft YaHei`, sans-serif 回退链。
- 页面标题使用 16px / 650，正文使用 14px 级别，辅助信息不小于 10px。
- 不再使用 serif 岗位标题，避免与 Chrome 原生 Side Panel 品牌栏竞争。

### 3.3 形状与层级

- 小控件圆角为 8–10px，User Message 和 Artifact 为 12–14px。
- 一般内容不使用阴影；Artifact 允许一层很浅的投影。
- 区域分隔使用单像素冷灰线，不叠加粗边框。
- 交互过渡为 120–160ms；`prefers-reduced-motion` 时禁用非必要过渡。

## 4. 布局

Side Panel 继续使用三行 Grid：

```text
Page Header      auto
Timeline         minmax(0, 1fr), scrollable
Composer         auto, sticky visual anchor
```

### 4.1 Page Header

- Chrome 原生 Side Panel 栏已经显示 Agent Bridge 图标与名称，应用内不重复品牌栏。
- 只展示岗位或页面标题、来源链接和可选匹配分数。
- 标题最多两行；分数是紧凑 pill，不压缩标题至无法阅读。

### 4.2 Timeline

- Assistant Message 不显示背景卡片或边框，作为主要阅读内容。
- User Message 右对齐，使用 Brand Soft 气泡，最大宽度为可用空间的 82–84%。
- 每条消息继续显示本地时间，不显示“你”或“Agent”角色标签。
- Markdown 标题、列表和段落使用更宽松的垂直节奏。表格使用独立白色表面，代码块和
  表格只在自身内横向滚动。
- Cover Letter 和 CV Attachment 继续嵌套在生成它的 Assistant Message 中，只有
  Artifact 使用独立白卡。

### 4.3 Empty State

空状态必须根据 Workspace 是否已连接分成两种，不得使用同一条误导文案。

**Connected empty**：Workspace state 存在但尚无历史，Timeline 显示垂直居中的任务引导：

```text
小型紫色图形
从一个明确的任务开始
选择下方 Action，然后说明你想知道或修改什么。
```

此时 Composer 正常显示 Gateway 声明的 Actions。

**Disconnected / initial load**：尚无 Workspace state 时显示中性提示，说明需要先从
页面 Quick Insight 进入 Workspace；不提示用户选择尚不存在的 Action，Composer 保持禁用。
首次加载过程显示简短的“正在加载 Workspace”状态，Timeline 继续使用 `aria-busy`，
不生成伪 Message 或伪 Action。

断线框、大面积占位卡和额外 CTA 不在范围内。

### 4.4 Composer

- 顶部辅助行显示“下一步”与 `histories / 10`。
- Action 使用轻量 pill，允许多行换行，禁止横向滚动。
- `textarea` 与发送按钮组成一个 `input-shell`；发送按钮放在右下角。
- 聚焦时只增加紫色边框和浅色 focus ring，不改变布局。
- 错误、Retry 和 Extension Update 信息位于输入区附近，保留现有重试语义。
- 辅助行继续显示 Enter / Shift+Enter 提示或当前限制状态。

## 5. 交互与状态

不改变现有数据流和业务语义：

- Action 仍是下一条消息的强意图提示，切换 Action 不清空历史。
- 加载期间禁用 Action、textarea 和发送按钮，不清空用户草稿；已有 state 时
  保留时间线，首次加载时使用 disconnected loading 提示。
- 请求失败保留输入内容和既有 Workspace state，Retry 重用同一条指令。
- 新历史到达后自动滚动至最后一条；资源、tab 或 owner 变化时继续使用现有隔离逻辑。
- 达到消息限制后保留完整历史和 Artifact，禁用继续发送。

## 6. 实现边界

实施仅涉及 Extension 视图层：

| 文件 | 变更 |
| --- | --- |
| `extension/sidepanel.html` | 增加 `input-shell` 组合层，保留现有稳定 id |
| `extension/sidepanel.css` | 替换视觉 token，重做 Header、Timeline、Message、Artifact、Composer 和响应式布局 |
| `extension/sidepanel.js` | 仅补充 Empty State 结构化渲染，不改变 Workspace 生命周期逻辑 |
| `extension/sidepanel.test.js` | 补充新 DOM、Empty State、Composer 和视觉约束测试 |
| `extension/fonts/` | 增加本地 DM Sans WOFF2 和对应授权文件 |
| `extension/package.sh` | 将 `fonts/` 加入显式发布白名单 |
| `extension/scripts/verify-package.mjs` | 校验字体与授权文件进入 zip，且 CSS 不引用远程字体 |
| `extension/README.md` | 更新 Quiet Precision 视觉与本地字体说明 |

必须保留所有 JS 依赖的 id，包括 `workspace-title`、`match-score`、`source-link`、
`timeline`、`action-chips`、`message-input`、`composer-error`、`turn-meter` 和 `send-button`。

## 7. 可访问性与响应式

- 保留语义化 `header`、`section`、`footer`、`form`、`label`、`time` 和实际 `button`。
- Action 继续通过 `aria-pressed` 暴露选中状态，错误继续使用 `role="alert"`。
- 交互元素使用 `:focus-visible`，聚焦不能只依赖颜色变化。
- 正文、辅助文字和主要操作颜色需满足 WCAG AA 对比度。
- 359px 及以下减少水平 padding，但不改变 Action 换行和 Message 对齐语义。
- 超长标题、URL、Markdown、Artifact 标题和 User Message 都不得推动整个面板横向溢出。

## 8. 测试与验收

### 自动化测试

- 新 Composer DOM 保留所有稳定 id，发送、Action 切换和错误重试测试继续通过。
- Connected empty 渲染任务引导；disconnected 与 initial loading 渲染各自的中性提示，
  不渲染伪 Message、伪 Action 或误导文案。
- Assistant 无角色标签，User Message 仍以纯文本渲染，Assistant 仍使用净化 Markdown。
- Attachment 继续位于其 Assistant Message 中，Cover Letter 复制和 CV 新标签打开行为不变。
- Action 使用 `flex-wrap`，Timeline 和 Shell 没有横向溢出，Markdown table / pre / code 内部可滚动。
- `prefers-reduced-motion`、`:focus-visible` 和小宽度 media query 仍然存在。
- Extension 单元测试、package 测试和打包流程通过；zip 显式包含本地 WOFF2
  和字体授权文件，且发布 CSS 不包含远程 `@import` 或远程字体 URL。

### 手动验收

- 在 280px、400px 和 600px 面板宽度验证空 Workspace、多轮对话、表格、长代码块、
  Cover Letter Artifact、CV Artifact 和错误重试状态。
- 空状态有清晰的开始焦点，不再显示大面积无结构留白。
- Assistant 内容是时间线中的主视觉，User Message 和 Artifact 可以快速被区分。
- Composer 在完成 Action 切换、输入、发送和 Retry 时不跳动，键盘操作与焦点顺序正确。
- 页面内部不重复显示 Agent Bridge 品牌栏，与 Chrome 原生 Side Panel 栏形成一个完整层级。

## 9. 发布边界

该变更是 Extension 包内的视图层更新。代码合并到 `main` 不等于 Chrome 用户已经获得
新界面；仍需提升 `manifest.json` 发布版本、打包并通过 Chrome Web Store 审核。
