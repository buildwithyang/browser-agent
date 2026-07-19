# Agent Bridge 浏览器扩展

Agent Bridge 先用 Quick Insight 回答“当前页面最值得关注什么”，再把用户选择的 Action 打开到 Chrome Side Panel。Side Panel 是同一网页资源的共享 Workspace：所有 Action 共用一份历史，并可展示当前生成的文档，不需要重复页面上下文。

> 本 README 描述当前仓库中的扩展实现。云端 `/tasks/workspace` 部署和 Chrome 应用商店发布需要分别完成，不能仅凭源码状态判断线上版本已经具备 Side Panel。

## 交互流程

```text
右键 Browser Agent
  ↓
content.js 采集当前页面上下文
  ↓
POST /tasks/quick-insight
  ↓
网页浮层显示 Quick Insight + 后端声明的 Actions
  ↓ 选择 Action
Side Panel 加载本地 Workspace
  ↓
POST /tasks/workspace
  ↓
用后端返回的完整 histories / document 替换本地状态
```

Quick Insight 始终先于聊天出现。用户在浮层选择 Action 后才进入 Side Panel；切换 Action 只决定下一条消息采用哪种任务能力，不会新建聊天或清空历史。

## 页面路由与 Actions

扩展不判断页面属于哪个 Agent，也不在公开请求中发送 `agent`。Context Routing 和业务资源 URL 归一化都在网关完成，因此后端可更新规则而无需重新发布扩展。

- LinkedIn / Indeed：host 匹配且选中的 JD 达到岗位分析要求时，网关路由到岗位匹配，并声明 `Analyze`、`Tailor Resume`、`Generate Cover Letter`、`Ask More`。
- 其他页面或不完整的岗位上下文：路由到通用页面摘要，并只声明 `Ask More`。
- 岗位 Workspace 默认选中 `Analyze`；普通网页默认选中 `Ask More`。

Action 由 Quick Insight 响应返回，Side Panel 只负责平铺渲染，不写死网站能力集合。

## 一个资源，一个本地 Workspace

Workspace 按“owner + 规范化 `resourceUrl`”存入 `chrome.storage.local`：

```text
agent-bridge:workspace:v1:<owner>:<resourceUrl>
```

- 登录用户使用网关签发的稳定 `user_id` 作为 owner；匿名自部署使用 `anonymous`。
- LinkedIn 的同一 `currentJobId` / `/jobs/view/{id}` 会进入同一 Workspace。
- Indeed 的同一 `jk` / `vjk` 会进入同一 Workspace。
- 普通网页会移除 fragment 和 `utm_*`，并稳定排序其余查询参数。
- 同一用户、同一业务资源可在扩展重新加载后恢复；不同用户或不同资源不会读取彼此的历史。
- Workspace 只保存在当前 Chrome 配置中，不做服务端 Thread 或跨设备同步。

Workspace 持久化 `Quick Insight`、Actions、选中 Action、完整 `histories` 和当前 `currentDocument`。每个响应都会整体替换文档字段；`Ask More` 不生成新产物，但网关会回传并保留已有文档。尚无文档时才返回 `document: null`。整页正文、当前选区和图片文字线索不会写入长期 Workspace；每次发送前都从当前标签页重新采集。

## 共享历史与消息上限

Side Panel 只展示一条按时间排列的共享历史，不按 Action 分组。网关每次返回完整的新 `histories`，扩展整体替换本地历史，不在客户端自行 append Assistant 消息。

发送前后端都会校验：

```text
len(histories) + 1 <= 10
```

其中 `1` 是当前用户消息。最后一次合法请求的 Assistant 回复仍会写入完整历史，因此最终本地时间线最多可有 11 条；达到上限后保留历史和最新文档，但不再允许继续发送。本期不截断或总结历史。

## 登录身份与最小并发规则

网页端通过 `externally_connectable` 一次性推送 bearer token、过期时间和 `user_id`，扩展原子保存这三个值。`/tasks/quick-insight` 和 `/tasks/workspace` 自动携带 bearer token；本地网关可在 `REQUIRE_AUTH=false` 时匿名运行。

每个 Workspace 请求会捕获开始时的 owner/token 快照：

- 响应返回时如果当前 `user_id` 已不同，直接丢弃响应，不写入旧用户或新用户的 Workspace，并通知 Side Panel 重置。
- 旧请求返回 401 时，只有当前 owner 和 token 仍与请求快照一致才清理登录态；否则把它当作过期响应丢弃。
- 同一 `user_id` 下的 OPEN/SEND 顺序竞态，以及用户 A → B → A 的 ABA 场景不在本期并发保证范围内。

## 扩展采集与发送的数据

`content.js` 只采集纯文本，不发送图片像素、HTML、CSS 或脚本：

| 字段 | 来源 | 说明 |
|---|---|---|
| `url` | `location.href` | 页面原始地址 |
| `title` | `document.title` | 标签页标题 |
| `selectedText` | 右键选区 / `getSelection()` | 用户选中的文字 |
| `pageText` | `document.body.innerText` | 可见文字，压缩空白后截断 |
| `imageText` | `alt` / `title` / `figcaption` / `aria-label` | 图片的纯文字线索，不含图片本身 |

Quick Insight 请求再附加 `lang`。Workspace 请求使用最新页面上下文，并附加：

- `resourceUrl`
- `actionId`
- 完整 `histories`
- 最新 `currentDocument` 的 `kind`、`title`、`text`
- 当前 `message`
- `lang`

公开请求均不包含 Agent 选择器。`POST /tasks/current-task` 从未发布且已移除；扩展只使用 `POST /tasks/quick-insight` 和 `POST /tasks/workspace`。线上已发布的旧 `POST /tasks` 仅供旧扩展兼容。

## 语言与网关

popup 只控制输出语言：`跟随浏览器（默认）`、`中文`、`English`。偏好存在 `chrome.storage.sync`，每次请求实时解析。

普通用户不能配置 `gatewayUrl`：

- 从源码加载未打包的 `extension/`：`http://127.0.0.1:17321`
- `package.sh` 生成的商店包：`https://browser.buildwithyang.com/api`

遇到有效的 401，扩展会清除当前登录态并引导用户回到网页端重新连接。

## 主要文件

| 文件 | 作用 |
|---|---|
| `manifest.json` | MV3 清单、Side Panel、权限、固定扩展 ID 和网页连接范围 |
| `background.js` | Quick Insight 请求、Workspace 编排、鉴权快照、Side Panel 打开与消息路由 |
| `content.js` | 采集当前标签页纯文本上下文 |
| `quick-insight.js` | 将 typed Insight 和 Actions 归一化为浮层视图数据 |
| `sidepanel.html` / `sidepanel.css` / `sidepanel.js` | 共享历史、最新文档、Action chips 和固定输入区 |
| `workspace.js` | owner/resource 存储键、Workspace reducer 与消息上限校验 |
| `workspace-controller.js` | tab 会话映射、鉴权快照、响应应用与恢复规则 |
| `popup.html` / `popup.js` | 输出语言偏好 |
| `auth.js` | token/owner 存取、公开请求 body、鉴权头与 401 判定 |
| `config.js` | 源码与打包产物的本地/云端网关选择 |
| `package.sh` | 生成 Chrome 应用商店 zip |

## 安装与使用

扩展 manifest 内置固定 `key`，扩展 ID 为 `cmajoaedbjinocbfdkebaedkdbkhbhai`。网页端据此连接扩展。

### Chrome 应用商店

1. 打开 [Chrome 应用商店页面](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai) 并添加扩展。
2. 登录网页端，在“浏览器扩展”卡片中连接扩展。
3. 打开页面；如需岗位匹配，先选中完整 JD。
4. 右键选择 `Browser Agent`，阅读 Quick Insight，再选择 Action 进入 Side Panel。

### 从源码加载

1. 在仓库根目录运行 `./dev-start backend`，或运行 `./dev-start` 同时启动网关和前端。
2. 打开 `chrome://extensions`，启用开发者模式并选择“加载已解压的扩展程序”。
3. 选择本仓库的 `extension/` 目录；修改后在扩展卡片上重新加载。

## 测试与打包

```bash
cd extension
npm test
npm run test:package
npm run package
```

`npm run package` 生成 `dist/agent-bridge-extension-<版本>.zip`。上传 Chrome 应用商店前需先递增 `manifest.json` 中的 `version`。打包产物只包含运行所需文件；`extension/key.pem` 不入库。

## 隐私

云端包会把当前页面文本、共享历史、最新文档，以及岗位匹配所需的生效简历发送到托管网关及其配置的模型服务。源码版把这些内容发送到本地网关，再由本地网关转发到 `gateway/.env` 配置的模型服务。

当前内部用户阶段的网关会把任务 URL、页面正文、完整 Prompt（岗位任务中可能包含 CV）和模型结果写入任务明细。面向公开用户部署前必须配置相应的数据库访问、脱敏和数据保留策略。

扩展不会把完整页面正文长期写入 Workspace，但会在当前 Chrome 配置中保存生成的 Quick Insight、聊天历史和最新文档。清除扩展本地存储会同时清除这些 Workspace。
