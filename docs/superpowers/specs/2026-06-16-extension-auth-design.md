# 扩展登录与 `/tasks` 鉴权方案

> 状态：**已定稿，待实现** · 日期：2026-06-16 · 关联模块：`gateway/app/modules/auth`、`gateway/app/modules/task`、`extension/`、`frontend/`

## 背景

扩展当前直接、**匿名**调用本地网关 `http://127.0.0.1:17321/tasks`（见 `extension/background.js`、`extension/manifest.json` 的 `host_permissions`）。一旦把网关挂到公网域名供平台用户使用，`/tasks` 就成了一个**匿名、无输入上限、花平台 LLM 钱**的公开接口——等于给全网开了个烧钱水龙头。

本方案解决：扩展如何带着**登录用户身份**调用云端 `/tasks`，从而能用该用户的简历、并按用户计费 / 限流。

## 关键约束（为什么不能简单复用 Web 登录态）

- Web 端登录用的是 Casdoor + 网关签名 **session cookie**（已实现，见 `auth` 模块）。
- 但扩展的后台 `fetch` 是**跨站**请求，`SameSite=lax` 的 session cookie **不会被发送**到网关。
- 所以扩展**必须改用 bearer token**：登录后拿到一个绑定 `user_id` 的 token，请求 `/tasks` 时带 `Authorization: Bearer <token>`。
- 问题的本质只剩一个：**token 怎么交到扩展手里**。

## 方案对比（token 交付管道）

| 方案 | 机制 | 适合 | 取舍 |
|---|---|---|---|
| **① externally_connectable**（选用）| 用户在前端正常登录后，**网页用 `chrome.runtime.sendMessage(扩展ID, {token})` 把 token 推给扩展** | 同时拥有网站和扩展 | 复用已有 Web 登录，扩展端最省；仅在「网页开着+扩展已装」时能传 |
| ② launchWebAuthFlow | 扩展在沙箱弹窗里自己跑完整 OAuth，从 `chromiumapp.org` 回调抠 token | 扩展独立分发、用户可能不开网页 | 不依赖网页；但要接回调、固定扩展 ID、代码更多 |
| ③ 复用 session cookie（`chrome.cookies`）| 扩展直接读网关域名 cookie 自行注入 | 想零 token 体系 | 偏 hack，SameSite 限制；不利于「按用户计费 + 可吊销」 |
| ④ 复制粘贴 token | 网页生成 token，用户手动粘进扩展 | 兜底 | 最稳但体验最差 |

> `chrome.identity.getAuthToken` 是 Google 账号专用，本项目用 Casdoor，排除。

## 决策：① externally_connectable + 自签 DB opaque bearer token

**理由**：不管哪种方案，扩展调 `/tasks` 终归要带 bearer token（cookie 跨站发不出去）。我们**已经做好了完整的 Web Casdoor 登录**，所以最划算的是用 externally_connectable 当「token 交付管道」，而不是再造一套 launchWebAuthFlow。

相比 ②：**不动 Casdoor、不接 `chromiumapp.org`、扩展端代码少一大半**。

### 目标流程

```text
用户在前端登录（已有的 Casdoor 流程，session cookie 落在网关同源）
   └─ 前端在登录态下调用  网关 POST /auth/extension-token   （cookie 鉴权，同源）
        └─ 网关签发绑定 user_id 的 bearer token，返回明文 token 给前端
   └─ 前端检测到扩展 → chrome.runtime.sendMessage(扩展ID, { token })
        └─ 扩展 onMessageExternal 收下 → 存入 chrome.storage
之后扩展调用 /tasks 时带  Authorization: Bearer <token>
   └─ 网关校验 token → 解析 user_id → 用该用户简历、按用户限流/计费
```

「网页没开 / 装扩展前就登录过」的兜底：前端加一个显式「连接扩展」按钮触发推送；或扩展需要时快速开一下前端 tab 再关。

## 已定决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| **token 模型** | **DB opaque token + `auth_tokens` 表** | 每次查库校验，可精确单个吊销 / 解绑设备，天然适配后期收费；与 `auth`/`resume` 现有 repo 模式一致。JWT 的「免查库」收益不抵「难吊销」代价。 |
| **有效期 / 刷新** | **长效（30 天）+ 可吊销 + 网页重推** | DB token 本就可吊销；前端在登录态下可随时经 `/auth/extension-token` + externally_connectable 静默重新签发推送——这条管道**本身就是刷新路径**，无需再造 refresh token。扩展遇过期/401 即请网页重推。 |
| **自部署单用户** | **`REQUIRE_AUTH=false` 时匿名直连、token 可选** | 自部署单用户不应被迫架 Casdoor。一个开关切两种模式，同一份网关代码通吃；保持自部署现有「无登录直连本地」体验不变。 |
| **token 存储形态** | **DB 只存 `sha256(token)`，不存明文** | 明文 token 仅在签发那一刻返回给前端；DB 泄露也拿不到可用 token，与「token 不落日志」安全基调一致。 |
| **解绑设备** | **后端 `GET` / `DELETE` 端点 v1 即做；前端管理 UI 延后** | 目标含「可解绑设备」，端点 DB 模型天然支持顺手做掉；但前端列表 UI 非首发刚需，延后到后续迭代。 |
| **前端连接触发** | **混合：检测到已装即静默自动推送 + 常驻手动按钮兜底** | 兼顾「无感连上」与「用户可控、可重试、过期自愈」；纯自动缺乏可控入口，纯手动则每次过期都要手动重连。 |

## 各端改动清单

### 网关（gateway）

**新增 `auth_tokens` 表**（model/repo + 同步 `deploy/initdb/001-schema.sql`）：

```
auth_tokens
  id            VARCHAR(32)  PK              -- token 记录 ID（uuid hex），用于「解绑设备」
  user_id       VARCHAR(32)  NOT NULL        -- 归属用户（auth_users.user_id）
  token_hash    VARCHAR(64)  NOT NULL        -- sha256(明文 token) 的十六进制
  label         VARCHAR(128)                 -- 设备/来源标识（如 "Chrome 扩展"）
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
  last_used_at  TIMESTAMPTZ                  -- 展示「最近使用」+ 判活
  expires_at    TIMESTAMPTZ  NOT NULL        -- 签发 + 30 天
  revoked       BOOLEAN      NOT NULL DEFAULT FALSE
  -- 唯一索引 uq_auth_tokens_token_hash (token_hash)
  -- 索引 idx_auth_tokens_user_created_at (user_id, created_at)
```

- 明文 token 形如 `ext_<secrets.token_urlsafe(32)>`；签发时返回明文，DB 落 `sha256`。

**端点（`auth` 模块）**：
- `POST /auth/extension-token`：登录态（cookie，复用 `require_auth_user`）下为当前用户签发 token，返回明文 token + `expires_at`。重复调用 = 重推 / 续期（落新行）。
- `GET /auth/extension-tokens`：列出本人 token（脱敏，仅 `id` / `label` / `created_at` / `last_used_at` / `expires_at` / `revoked`，**不返回明文或 hash**）。
- `DELETE /auth/extension-tokens/{id}`：吊销本人单个 token（置 `revoked=true`）。

**`/tasks` 鉴权改造**：
- 统一在 auth 层做 `resolve_user_id(request) -> str | None`：**先看 `Authorization: Bearer`（查 `auth_tokens`，校验未吊销且未过期，命中刷新 `last_used_at`），再回退 session cookie**。
- `task` 模块调用 `resolve_user_id` 拿 `user_id | None`，替换现有 `_current_user_id` 逻辑。
- 新增 `REQUIRE_AUTH` 开关，行为矩阵：

| | `REQUIRE_AUTH=true`（托管平台） | `REQUIRE_AUTH=false`（开源自部署默认） |
|---|---|---|
| 无凭证 | **401** | ✅ 匿名，`user_id=NULL`，本地简历回退 |
| Bearer token | 校验 → 解析 `user_id` → 按用户简历 / 计费 / 限流 | 同左（token 可选，可用则用） |
| session cookie | 接受（同源 Web 调用） | 接受 |

**配套（与本方案同批做）**：
- 输入封顶：`page_text` / `selected_text` / `image_text` 加 `max_length`。
- 按 `user_id` 限流 / 配额：复用已有 `task_records` 做计数底座（已带 `user_id` 列与 `idx_task_records_user_created_at` 索引），超额返回 429。

### 前端（frontend）

- 登录态下调用 `/auth/extension-token` 取 token，`chrome.runtime.sendMessage(扩展ID, { type: "AUTH_TOKEN", token })` 推送给扩展。
- 在现有单页卡片栈（[App.jsx](../../../frontend/src/App.jsx)，登录态下 `上传简历` / `我的简历` 两张卡）中**新增一张「浏览器扩展」卡片**，承载探测 / 连接 / 状态回显。详见下文「前端交互」。
- **解绑设备 UI 延后**：后端 `GET` / `DELETE /auth/extension-tokens` 端点 v1 即做（见上），但前端的「已连接设备」管理界面**不在 v1 范围**，列入开放项 / 后续迭代。

### 扩展（extension）

- `manifest.json`：加 `"externally_connectable": { "matches": ["https://*.<域名>/*"] }`；`host_permissions` 增加网关域名；`GATEWAY_URL` 改为**可配置**（`chrome.storage`，托管默认云域名 / 自部署填本地）。
- `background.js`：`chrome.runtime.onMessageExternal` 处理三类消息——
  - `PING`：回 `PONG` 并报告**当前是否持有有效 token**（供前端区分「已装未连」/「已连」）。
  - `AUTH_TOKEN`：收 token 存 `chrome.storage`，并在 `sendResponse` 里**回 ack**（供前端确认连接成功）。
- `/tasks` 请求带 `Authorization: Bearer`；遇 401 触发「请在网页端登录并连接扩展」。
- token 存储：敏感优先 `chrome.storage.session`（内存、浏览器关闭即清，需重连）；要持久登录用 `chrome.storage.local`。MV3 service worker 不能用全局变量存状态。

### Casdoor

- **无需改动**：OAuth 回调仍是网关已登记的 `/auth/callback`，扩展流程不经过 Casdoor。

## 前端交互（扩展连接卡片）

前端是单页卡片栈，无路由。扩展连接作为登录态下的**第三张卡片**接入，不引入路由改动。

### 触发方式：混合（自动 + 手动兜底）

检测到扩展已装但未连接时，**静默自动推送一次**；同时卡片上常驻「连接 / 重新连接」按钮做兜底。兼顾「无感连上」与「用户可控、可重试」。

### 卡片状态机

卡片在 `me` 就绪后向扩展 `chrome.runtime.sendMessage(扩展ID, { type: "PING" })` 探测，按结果切换：

| 状态 | 触发条件 | 展示 |
|---|---|---|
| 检测中 | PING 已发、未回 | 「检测中…」 |
| 未安装 | 无 `chrome.runtime` / 报错 / 超时 | 「未检测到扩展」+ 安装链接 |
| 已装·未连接 | PONG 返回但无有效 token | 「连接扩展」按钮（并自动推一次） |
| 已连接 | token 推送成功（收到 ack）/ PONG 报告已持有 | 「已连接 ✓ + 最近连接时间」+「重新连接」 |

```text
[me 就绪] → PING 扩展
   ├─ 无响应/报错 → 未安装（给安装链接）
   └─ PONG ─┬─ 已持 token → 已连接
            └─ 无 token → 自动 POST /auth/extension-token → sendMessage 推送
                            └─ 收到 ack → 已连接
```

### 连接数据流

```text
前端 POST /auth/extension-token（cookie 鉴权）
   └─ 网关签发 → 返回明文 token
前端 chrome.runtime.sendMessage(扩展ID, { type: "AUTH_TOKEN", token })
   └─ 扩展 onMessageExternal 存入 chrome.storage → sendResponse(ack)
前端收 ack → 卡片切「已连接」
```

### 过期自愈

扩展遇 401 无法主动通知前端；改由前端**每次加载探测到扩展已装时静默重签发 + 重推一次**（token 重推无害、成本低），用户基本无感地保持连接。扩展侧 401 时在 popup 提示「请在网页端登录并连接扩展」。

### 对扩展侧的隐含要求

本交互要求扩展 `onMessageExternal` 额外支持：**`PING`→`PONG`（含「是否持有有效 token」标志）握手**，以及 **`AUTH_TOKEN` 的 `sendResponse` ack 回执**。已并入「扩展（extension）」改动清单。

## 安全注意事项

- token 经消息通道传递，**不进 URL query、不落日志**（日志脱敏已是 `AGENTS.md` 约束）。
- DB 只存 `sha256(token)`，明文仅签发时返回一次。
- `externally_connectable.matches` 严格限定到自有域名；`matches` 不支持通配 TLD。
- 扩展 ID 固定（开发期 manifest 加 `key`，上架后 ID 本就稳定），前端按已知扩展 ID 推送。
- 全程 HTTPS；CORS 仅为真实前端 Origin 开 credentials（扩展走 `host_permissions`，不依赖 CORS）。
- token 可在前端「解绑设备」精确吊销。

## 实施步骤

- [x] 网关：`auth_tokens` 表 + model/repo（含 `sha256` 存储），同步 `deploy/initdb/001-schema.sql`
- [x] 网关：`POST /auth/extension-token`（登录态下签发，返回明文）
- [x] 网关：`GET /auth/extension-tokens` + `DELETE /auth/extension-tokens/{id}`（解绑设备）
- [x] 网关：auth 层 `resolve_user_id`（Bearer 优先、cookie 回退，命中刷新 `last_used_at`）
- [x] 网关：`/tasks` 接入 `resolve_user_id` + `REQUIRE_AUTH` 开关
- [x] 网关：输入封顶（`max_length`）+ 按用户限流（复用 `task_records`，超额 429）
- [ ] 前端：新增「浏览器扩展」卡片（PING 探测 + 4 态 + 混合触发：自动推送 + 手动按钮 + 过期自愈重推）
- [ ] 扩展：`externally_connectable` + `onMessageExternal`（`PING`/`PONG` 握手 + `AUTH_TOKEN` ack）+ token 存储 + `Authorization` 头 + 可配置域名
- [ ] （延后，非 v1）前端「已连接设备」管理界面（解绑），调用 `GET` / `DELETE /auth/extension-tokens`
- [ ] 文档：更新 `extension/README` 与 `auth`/`task` 模块 README，本 spec 转「已实施」

## 参考

- [externally_connectable | Chrome for Developers](https://developer.chrome.com/docs/extensions/reference/manifest/externally-connectable)
- [Authenticate your chrome extension user through your web app (Medium)](https://medium.com/the-andela-way/authenticate-your-chrome-extension-user-through-your-web-app-dbdb96224e41)
- [Share login between webapp and chrome extension (chromium-extensions group)](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/c1_arP74-FI)
- [chrome.storage | Chrome for Developers](https://developer.chrome.com/docs/extensions/reference/api/storage)
- [Chrome Extension (Manifest v3) — using Auth0 securely (Auth0 Community)](https://community.auth0.com/t/chrome-extension-manifest-v3-using-auth0-in-a-secure-manner/125433)
