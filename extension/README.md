# Agent Bridge 浏览器扩展

Agent Bridge 先用 Quick Insight 回答“当前页面最值得知道什么”，再把用户选择的 Prompt
Shortcut 填入 Chrome Side Panel。Side Panel 是当前网页资源的共享 Workspace：所有
Shortcut 共用一份时间线、最新 CV 和 Cover Letter。

> Gateway 部署与 Chrome 应用商店发布是两个独立步骤。协议不兼容时应先更新扩展，
> 不能只凭本地源码判断商店版本已更新。

## 使用流程

```text
右键 Browser Agent
  -> POST /tasks/quick-insight（普通 JSON）
  -> 页面浮层显示 Insight + Prompt Shortcuts
  -> 打开同一资源的 Side Panel
  -> Shortcut 只填充输入框，用户编辑后发送
  -> POST /tasks/workspace（protocol v4 NDJSON）
  -> 增量展示本轮进度
  -> completed.response 成为 canonical Workspace
```

- Quick Insight 的 Shortcuts 使用紧凑标签，空间不足时自动换行。
- Side Panel 使用 Quiet Precision 浅色工作台，Assistant Markdown 无气泡，User Message
  使用轻紫背景，Artifact 作为 Assistant Message 的 Attachment 展示。
- Chrome 不提供设置 Side Panel 默认宽度的 API；用户可拖动边界，布局会适配窄面板。
- 英文与数字使用扩展包内的 DM Sans WOFF2，不在运行时请求远程字体。

## 页面与 Prompt Shortcuts

扩展不发送公开 `agent` 参数。Gateway 根据当前页面选择能力并规范化资源 URL，因此后端
可以调整站点规则而无需把路由逻辑发布到扩展。

- LinkedIn / Indeed 完整岗位：`Analyze`、`Tailor Resume`、
  `Generate Cover Letter`、`Ask More`。
- 其他页面或不完整岗位上下文：页面摘要和 `Ask More`。

点击任何 Shortcut 都只会打开同一 Workspace、用服务端返回的本地化 Prompt 替换输入框
并聚焦，不调用 Workspace 接口，也不会自动发送。`Ask More` 的 Prompt 为空，因此会清空
输入框。用户编辑并发送后，Agent 只根据最终消息、当前 Artifact 与共享历史规划本轮结果。

## 一个资源，一个本地 Workspace

canonical state 按 owner 与 Gateway 返回的 `resourceUrl` 保存在
`chrome.storage.local`：

```text
agent-bridge:workspace:v3:<owner>:<resourceUrl>
```

- 登录用户使用稳定 `user_id`；匿名自部署使用 `anonymous`。
- LinkedIn 同一 job id、Indeed 同一 `jk` / `vjk` 会进入同一 Workspace。
- 普通网页移除 fragment 和 `utm_*`，稳定排序其余 query。
- 不同 owner 或不同资源不能读取彼此的 state。

本地只长期保存最近 Quick Insight、Shortcuts、完整 histories 与最新 `artifacts.cv` /
`artifacts.cover_letter`。页面正文、选区和图片文字线索在发送前从当前标签页重新采集，
不写入 Workspace。当前没有服务端 Thread、Artifact Repository 或跨设备 Workspace 同步。

schema v3 不转换旧本地 Workspace schema。`WORKSPACE_GET` 遇到当前 owner/resource 的
精确旧 record，或 tab mapping 指向非 v3 record 时，只丢弃该 record 与 mapping，并返回
未连接状态；下一次 Quick Insight seed 才创建全新的 v3 Workspace。旧 histories 和
Artifacts 不保留，也不会扫描其他 owner 或 resource。

pure v4 canonical history 只包含完整、按顺序排列的 User/Assistant pair，唯一上限为 20 条
history / 10 个 User turn。第 10 次发送允许，第 11 次被前后端拒绝；pending 立即计入
`10 / 10`，失败后恢复。达到上限时 Shortcut、输入框与发送按钮禁用并隐藏键盘提示，但
完整历史、Attachment 和复制控件仍然可用。

## Streaming 与 canonical commit

发送消息时，Side Panel 立即显示一个 optimistic User Message 和 transient Assistant 行；
它们不会提前写入 `chrome.storage.local`。Workspace NDJSON 事件按
`operation_id + sequence` 校验：

- `started`：建立本轮临时状态。
- `status`：显示 routing、generating 或 finalizing 进度。
- `delta`：只用于普通 reply，累积为增量 Markdown，最多每 50ms 合并一次绘制。
- `completed`：携带完整 canonical `response`。
- `failed`：终止本轮，不携带 next state。

Parser 还维护独立生命周期状态机：只接受可选 `routing`、一个
`generating_reply | generating_artifact`、`finalizing` 和终态的单向序列，并将终态
`result_type` / Attachment 类型与 generation mode 交叉校验。即使 Gateway 回归输出非法
Artifact delta，Extension 也不会渲染或持久化该 draft。

只有完整 stream 通过 UTF-8、NDJSON、事件 schema、顺序、终态和 protocol 校验后，
Extension 才把 `completed.response` 交给 `applyWorkspaceResponse()`。写入完成前 keyed queue
不会释放；写入完成后 Side Panel 重新加载 canonical history。刷新 Side Panel 时，成功
终态仍存在；transient delta 不会变成历史消息。

### Reply 与 Artifact 的可见性

- 普通 reply 会边生成边显示 Markdown。
- CV / Cover Letter Artifact 生成只显示状态，不显示产物 draft token。
- CV / Cover Letter 仅在成功终态以 Attachment 出现。
- Cover Letter Attachment 保存该版本的完整纯文本；后续更新不会修改旧版本。
- CV Attachment 打开 Gateway 返回的绝对 HTTP(S) URL，最新 draft 保留在 Artifact 中供
  下一轮修改。

当前 Gateway 的 CV Attachment URL 仍是临时预览入口，不代表本轮 CV 已按用户隔离、
托管或版本化。

### 失败恢复

模型失败、非法输出、断流、超时、取消、owner 变化或本地持久化失败时：

- 不 append canonical histories，不更新 Artifact；
- 恢复用户原始输入，保留可重试提示；
- 临时 Assistant 行显示失败状态，不把已收到的 delta 当作成功结果；
- 新操作、tab/resource/owner 变化会淘汰旧 operation，迟到事件不能覆盖新 Workspace；
- 迟到的 401 只有仍匹配请求时的 owner/token 才能清除当前登录态。

## Markdown

Workspace 的 Assistant reply 使用 Markdown。扩展随包携带 Marked 和 DOMPurify：先转换
HTML，再净化后插入 Side Panel，不依赖 CDN。支持标题、强调、列表、链接、代码和 GFM
表格。User Message 与 Cover Letter Attachment 始终按纯文本渲染，后者可直接复制。

Quick Insight 使用独立 typed cards；普通网页摘要 card 的 `body_html` 已由 Gateway 生成
并净化，不属于 Workspace streaming Markdown。

## Extension ↔ Gateway protocol v4

Quick Insight 与 Workspace 请求都携带：

```http
X-Agent-Bridge-Protocol-Version: 4
```

Workspace 另外发送 `Accept: application/x-ndjson`，并要求响应
`Content-Type: application/x-ndjson`。Quick Insight 仍是普通 JSON。两种成功响应都要求
protocol Header；JSON body 或 Workspace `completed.response` 还必须包含
`protocol_version: 4`。

Gateway 返回 `426 Upgrade Required`，或版本 Header/body 缺失、不一致时，扩展会显示
Chrome Web Store 更新入口，不清除登录态，也不覆盖 Workspace。protocol 版本是 wire
contract 整数，与 `manifest.json` 发布版本独立。旧 `POST /tasks` 不再生成内容。

云端 Nginx 必须对精确路径 `/api/tasks/workspace` 关闭 `proxy_buffering` 与
`proxy_cache`，否则 reply delta 可能延迟到终态后一次到达。Gateway 同时返回
`X-Accel-Buffering: no`。

## 扩展采集的数据

`content.js` 只采集纯文本，不发送图片像素、HTML、CSS 或脚本：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `url` | `location.href` | 页面原始地址 |
| `title` | `document.title` | 标签页标题 |
| `selectedText` | 右键选区 / `getSelection()` | 用户明确选中的文字 |
| `pageText` | `document.body.innerText` | 可见文字，压缩空白后截断 |
| `imageText` | `alt` / `title` / `figcaption` / `aria-label` | 图片的纯文字线索 |

Workspace 请求另外带 `operationId`、`resourceUrl`、完整 histories、两个 Artifact 槽位，
以及必填的最终 `message`。请求不会携带 Shortcut id；Shortcut 点击本身不发送请求。

## 登录与网关

网页通过 `externally_connectable` 推送 bearer token、过期时间和 `user_id`。两个 Task
接口自动携带 token；本地 Gateway 可在 `REQUIRE_AUTH=false` 时匿名运行。

普通用户不能配置 `gatewayUrl`：

- 从源码加载：`http://127.0.0.1:17321`
- 商店包：`https://browser.buildwithyang.com/api`

## 主要文件

| 文件 | 作用 |
| --- | --- |
| `background.js` | Quick Insight、Workspace keyed queue、stream 生命周期与 canonical commit |
| `workspace-stream.js` | protocol v4 NDJSON 增量解析和严格事件校验 |
| `workspace-operation.js` | operation command、顺序、取消与 terminal 应用边界 |
| `workspace.js` | canonical state 与 Message / Artifact / Attachment 校验 |
| `workspace-controller.js` | owner/resource 存储、协议、tab 映射与 transient snapshot |
| `sidepanel.html` / `.css` / `.js` | optimistic turn、Markdown、Attachment 和失败恢复 |
| `quick-insight.js` | typed Insight 与可编辑 Prompt Shortcut 语义 |
| `content.js` | 当前标签页纯文本采集 |
| `markdown.js` / `vendor/` | 本地 Marked + DOMPurify 渲染边界 |
| `auth.js` / `config.js` | 鉴权快照、Gateway 与 protocol 常量 |
| `package.sh` | allowlist 打包 Chrome 应用商店 ZIP |

## 安装与使用

扩展 ID：`cmajoaedbjinocbfdkebaedkdbkhbhai`。

### Chrome 应用商店

1. 从 [Chrome 应用商店](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai)安装扩展。
2. 登录网页端，在“浏览器扩展”卡片中连接扩展。
3. 打开页面；岗位匹配时先选中完整 JD。
4. 右键 `Browser Agent`，阅读 Quick Insight，选择 Shortcut，检查或编辑后再发送。

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

`npm run package` 生成 `dist/agent-bridge-extension-<版本>.zip`。包使用显式 allowlist，
包含 `workspace-stream.js` 和本地 Markdown/字体资产，不包含 tests、`node_modules` 或远程
runtime import。上传商店前需递增 `manifest.json` 的 `version`。

## 隐私

云端包会把当前页面文本、完整 Workspace state 和岗位匹配所需的生效 CV 发送到托管
Gateway 及其配置的 Chat Completions 服务。源码版发送到本地 Gateway，再由本地 Gateway
转发到 `.env` 配置的服务。

Quick Insight、Shortcuts、histories 与 artifacts 保存在当前 Chrome 配置中。Gateway
启用数据库时仍可能保存页面、Prompt 和模型结果；部署方必须设置访问控制、脱敏与保留策略。
