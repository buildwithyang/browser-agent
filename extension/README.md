# Agent Bridge 浏览器扩展

Agent Bridge 先用 Quick Insight 回答“当前页面最值得知道什么”，再把用户选择的 Action
带进 Chrome Side Panel。Side Panel 是同一网页资源的共享 Workspace：所有 Action 共用
一份时间线，用户不需要重复页面、岗位或前序产物上下文。

> 本 README 描述当前仓库中的扩展实现。Gateway 部署与 Chrome 应用商店发布是两个
> 独立步骤，不能只凭源码状态判断线上版本已经更新。

## 交互流程

```text
右键 Browser Agent
  ↓
采集当前页面纯文本
  ↓
POST /tasks/quick-insight
  ↓
页面浮层显示 Quick Insight + Actions
  ↓ 选择 Action
打开同一资源的 Side Panel Workspace
  ↓
POST /tasks/workspace
  ↓
用 Gateway 返回的完整 histories + artifacts 替换本地状态
```

- Quick Insight 的 Actions 使用紧凑标签，在空间不足时自动换行。
- Side Panel 使用 Quiet Precision 浅色工作台：冷中性色背景、品牌紫交互状态、
  无气泡 Assistant 正文、轻紫 User Message 和 Artifact-only 卡片。
- 无历史时显示居中任务引导；底部 Composer 把发送按钮集成到输入框，Action
  仍在上方自动换行。
- Chrome 不提供设置 Side Panel 默认宽度的 API；布局会适配常见窄宽度，用户可以拖动
  面板边界。
- Side Panel 英文与数字使用扩展包内的 DM Sans WOFF2，不会运行时请求远程字体。

## 页面路由与 Actions

扩展不判断页面属于哪个 Agent，也不发送公开 `agent` 参数。Context Routing 和业务资源
URL 归一化都由 Gateway 完成，因此后端可以调整网站规则而无需为路由逻辑重新发布扩展。

- LinkedIn / Indeed + 完整 JD：`Analyze`、`Tailor Resume`、
  `Generate Cover Letter`、`Ask More`，默认 `Analyze`。
- 其他页面或不完整岗位上下文：页面摘要 + `Ask More`，默认 `Ask More`。

Action 在两处有不同但明确的语义：

- **Quick Insight 点击：** `Analyze`、`Tailor Resume`、`Generate Cover Letter` 是确定性
  命令，打开 Workspace 后立即执行；`Ask More` 只打开并聚焦输入框。
- **Workspace 内选择：** Action 是下一条消息的强意图提示，不是强制产物命令。选中
  `Tailor Resume` 后询问“哪段经历最值得突出？”只得到建议；明确要求生成简历时才创建
  或更新 CV。

Action 列表由 Quick Insight 响应声明，浮层和 Side Panel 只按 `id + title` 渲染。

## 一个资源，一个本地 Workspace

Workspace schema v2 按“owner + Gateway 规范化的 `resourceUrl`”保存在
`chrome.storage.local`：

```text
agent-bridge:workspace:v2:<owner>:<resourceUrl>
```

- 登录用户使用稳定 `user_id`；匿名自部署使用 `anonymous`。
- LinkedIn `/jobs/view/{id}` 与 `currentJobId={id}` 会进入同一 Workspace。
- Indeed 的同一 `jk` / `vjk` 会进入同一 Workspace。
- 普通网页移除 fragment 和 `utm_*`，并稳定排序其他 query 参数。
- 不同 owner 或不同资源不能读取彼此的本地 state。

本地 state 保存：

- 最近的 Quick Insight 与 Gateway 声明的 Actions；
- 当前选中的 Action；
- 完整 `histories`；
- 固定 key 的最新 `artifacts.cv` 与 `artifacts.cover_letter`。

页面正文、当前选区和图片文字线索不会长期写入 Workspace；发送前从当前标签页重新采集。
本期没有服务端 Thread、Artifact Repository 或跨设备 Workspace 同步。

### v1 → v2 本地迁移

访问仍指向旧 v1 state 的 Workspace 时，扩展会先写入并重新读取 v2 state，校验通过后
再切换 tab 映射并移除旧记录。迁移只保留能通过 v2 校验、且不带 Attachment 的纯文本
历史；旧 `currentDocument` 不迁移，也不会伪造 Artifact 历史。两个 Artifact 槽位初始化为
`null`。

## 多轮消息与 Artifact

Side Panel 只展示一条按时间排列的共享历史，不按 Action 分组。每条 Message 都显示
浏览器本地时间；用户消息和 Assistant 消息不显示“你”或“Agent”发送者标签。

Gateway 每轮返回完整 next state，扩展先校验 Message / Artifact / Attachment 的结构和
引用关系，再整体替换本地 histories 与 artifacts。请求失败、协议不兼容或 owner 已变化
时，现有 state 和输入框内容都不会被部分覆盖。

Artifact 作为生成它的 Assistant Message 内的 Attachment 展示：

- `cover_letter`：Attachment 保存该版本的完整 Markdown，可在历史原位置查看并复制；
  后续更新不会修改旧版本。
- `cv`：Attachment 打开 Gateway 返回的绝对 HTTP(S) URL；最新完整 Markdown draft 仍在
  Artifact 中供下一轮修改。

当前 Gateway 给 CV Attachment 返回固定测试地址 `https://browser.buildwithyang.com`。
它只是临时预览入口，不代表本轮真实 CV 已托管、按用户隔离或按版本保存。

### 10 条输入限制

- 普通发送要求 `len(histories) + 当前 message <= 10`，即最多 9 条历史。
- Quick Insight 自动 Action 没有 User Message，可携带最多 10 条历史。
- 最后一次合法请求的 Assistant Message 仍会保留，因此终态最多 11 条消息。
- 达到终态上限后保留历史和 Artifacts，但不再发送或自动生成；本期不截断、不总结。

## Markdown

Workspace 的 Assistant Message 和 Cover Letter Attachment 使用 Markdown。扩展随包携带
Marked 与 DOMPurify：先把 Markdown 转成 HTML，再净化后插入 Side Panel；不依赖 CDN。

支持标题、粗体、斜体、列表、链接、行内代码、代码块和 GFM 表格。表格与代码块在自身
内部滚动，不推动整个 Side Panel 横向溢出。User Message 始终按纯文本渲染。

Quick Insight 使用独立的 typed cards；普通网页摘要 card 的 `body_html` 已在 Gateway
生成并净化，不属于 Workspace Markdown 契约。

## Extension ↔ Gateway 协议版本

`POST /tasks/quick-insight` 与 `POST /tasks/workspace` 的每个请求都携带：

```http
X-Agent-Bridge-Protocol-Version: 2
```

扩展先校验响应 Header，再处理 401 或业务错误；成功响应还必须包含
`protocol_version: 2`。版本缺失或不一致、以及 Gateway 返回 `426 Upgrade Required` 时，
扩展显示 Chrome Web Store 更新入口，不清除登录态，也不覆盖当前 Workspace。

协议版本是 wire contract 整数，与 `manifest.json` 发布版本独立。旧 `POST /tasks` 已停止
生成内容，只返回更新提示；`POST /tasks/current-task` 从未上线且已删除。

## 扩展采集的数据

`content.js` 只采集纯文本，不发送图片像素、HTML、CSS 或脚本：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `url` | `location.href` | 页面原始地址 |
| `title` | `document.title` | 标签页标题 |
| `selectedText` | 右键选区 / `getSelection()` | 用户明确选中的文字 |
| `pageText` | `document.body.innerText` | 可见文字，压缩空白后截断 |
| `imageText` | `alt` / `title` / `figcaption` / `aria-label` | 图片的纯文字线索 |

Quick Insight 请求再附加 `lang`。Workspace 请求使用最新 Page Context，并附加
`trigger`、`resourceUrl`、`actionId`、完整 `histories`、两个 `artifacts` 槽位，以及普通
发送时的 `message`。

## 登录、网关与错误恢复

网页端通过 `externally_connectable` 推送 bearer token、过期时间和 `user_id`。两个 Task
接口自动携带 token；本地 Gateway 可在 `REQUIRE_AUTH=false` 时匿名运行。

同一 Workspace 的请求通过 keyed queue 串行执行，并在队列内重新读取最新 state。请求
开始时捕获 owner/token；响应回来后 owner 已变化会直接丢弃，迟到的 401 只有在 owner
和 token 仍匹配时才清理当前登录态。

普通用户不能配置 `gatewayUrl`：

- 从源码加载：`http://127.0.0.1:17321`
- 商店包：`https://browser.buildwithyang.com/api`

## 主要文件

| 文件 | 作用 |
| --- | --- |
| `background.js` | Quick Insight、Workspace 命令队列、鉴权快照与 Side Panel 消息路由 |
| `content.js` | 采集当前标签页纯文本上下文 |
| `quick-insight.js` | typed Insight 视图与 Quick Action 执行语义 |
| `sidepanel.html` / `.css` / `.js` | Quiet Precision 时间线、Attachment、Action chips 与 composer |
| `fonts/` | Side Panel 本地 DM Sans WOFF2 与 OFL 授权 |
| `workspace.js` | schema v2、完整 state 校验、v1 迁移与消息上限 |
| `workspace-controller.js` | owner/resource 存储、协议响应、tab 映射与并发边界 |
| `workspace-operation.js` | Quick Action / User Message command 与 keyed queue |
| `markdown.js` | 本地 Marked + DOMPurify 渲染边界 |
| `popup.html` / `popup.js` | 输出语言偏好 |
| `auth.js` | token/owner 存取和公开请求 body |
| `config.js` | 本地/云端 Gateway 与协议版本常量 |
| `package.sh` | 生成 Chrome 应用商店 zip |

## 安装与使用

扩展 ID 为 `cmajoaedbjinocbfdkebaedkdbkhbhai`。

### Chrome 应用商店

1. 从 [Chrome 应用商店](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai)安装扩展。
2. 登录网页端，在“浏览器扩展”卡片中连接扩展。
3. 打开页面；岗位匹配时先选中完整 JD。
4. 右键 `Browser Agent`，阅读 Quick Insight，再选择 Action。

### 从源码加载

1. 在仓库根目录运行 `./dev-start backend`，或运行 `./dev-start` 同时启动 Gateway 与前端。
2. 打开 `chrome://extensions`，启用开发者模式，选择“加载已解压的扩展程序”。
3. 选择仓库中的 `extension/`；修改后在扩展卡片上重新加载。

## 测试与打包

```bash
cd extension
npm test
npm run test:package
npm run package
```

`npm run package` 生成 `dist/agent-bridge-extension-<版本>.zip`。上传商店前需递增
`manifest.json` 的 `version`。打包检查会验证本地 Markdown 依赖与 import graph，不允许
运行时代码从 CDN 加载模块。

## 隐私

云端包会把当前页面文本、完整 Workspace state，以及岗位匹配所需的生效 CV 发送到托管
Gateway 及其配置的模型服务。源码版发送到本地 Gateway，再由本地 Gateway 转发到
`.env` 配置的模型服务。

完整页面正文不会长期写入 Extension Workspace，但 Quick Insight、histories 与 artifacts
会保存在当前 Chrome 配置中。Gateway 配置数据库时仍会写既有 task record，其中可能包含
页面、Prompt 和模型结果；部署方必须设置相应的访问、脱敏与保留策略。
