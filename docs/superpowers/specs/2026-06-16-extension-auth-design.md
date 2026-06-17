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
| **解绑设备** | **补 `GET` / `DELETE` 两个 token 管理端点** | 目标明确含「可解绑设备」，DB 模型天然支持，与签发同批做掉。 |

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

- 登录态下调用 `/auth/extension-token` 取 token。
- 检测扩展是否安装，`chrome.runtime.sendMessage(扩展ID, { type: "AUTH_TOKEN", token })` 推送；加「连接扩展」按钮兜底。
- （可选）「已连接设备」管理界面，调用 `GET` / `DELETE /auth/extension-tokens` 做解绑。

### 扩展（extension）

- `manifest.json`：加 `"externally_connectable": { "matches": ["https://*.<域名>/*"] }`；`host_permissions` 增加网关域名；`GATEWAY_URL` 改为**可配置**（`chrome.storage`，托管默认云域名 / 自部署填本地）。
- `background.js`：`chrome.runtime.onMessageExternal` 收 token 存 `chrome.storage`；`/tasks` 请求带 `Authorization: Bearer`；遇 401 触发「请在网页端登录并连接扩展」。
- token 存储：敏感优先 `chrome.storage.session`（内存、浏览器关闭即清，需重连）；要持久登录用 `chrome.storage.local`。MV3 service worker 不能用全局变量存状态。

### Casdoor

- **无需改动**：OAuth 回调仍是网关已登记的 `/auth/callback`，扩展流程不经过 Casdoor。

## 安全注意事项

- token 经消息通道传递，**不进 URL query、不落日志**（日志脱敏已是 `AGENTS.md` 约束）。
- DB 只存 `sha256(token)`，明文仅签发时返回一次。
- `externally_connectable.matches` 严格限定到自有域名；`matches` 不支持通配 TLD。
- 扩展 ID 固定（开发期 manifest 加 `key`，上架后 ID 本就稳定），前端按已知扩展 ID 推送。
- 全程 HTTPS；CORS 仅为真实前端 Origin 开 credentials（扩展走 `host_permissions`，不依赖 CORS）。
- token 可在前端「解绑设备」精确吊销。

## 实施步骤

- [ ] 网关：`auth_tokens` 表 + model/repo（含 `sha256` 存储），同步 `deploy/initdb/001-schema.sql`
- [ ] 网关：`POST /auth/extension-token`（登录态下签发，返回明文）
- [ ] 网关：`GET /auth/extension-tokens` + `DELETE /auth/extension-tokens/{id}`（解绑设备）
- [ ] 网关：auth 层 `resolve_user_id`（Bearer 优先、cookie 回退，命中刷新 `last_used_at`）
- [ ] 网关：`/tasks` 接入 `resolve_user_id` + `REQUIRE_AUTH` 开关
- [ ] 网关：输入封顶（`max_length`）+ 按用户限流（复用 `task_records`，超额 429）
- [ ] 前端：取 token + `sendMessage` 推送 +「连接扩展」按钮（可选设备管理界面）
- [ ] 扩展：`externally_connectable` + `onMessageExternal` + token 存储 + `Authorization` 头 + 可配置域名
- [ ] 文档：更新 `extension/README` 与 `auth`/`task` 模块 README，本 spec 转「已实施」

## 参考

- [externally_connectable | Chrome for Developers](https://developer.chrome.com/docs/extensions/reference/manifest/externally-connectable)
- [Authenticate your chrome extension user through your web app (Medium)](https://medium.com/the-andela-way/authenticate-your-chrome-extension-user-through-your-web-app-dbdb96224e41)
- [Share login between webapp and chrome extension (chromium-extensions group)](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/c1_arP74-FI)
- [chrome.storage | Chrome for Developers](https://developer.chrome.com/docs/extensions/reference/api/storage)
- [Chrome Extension (Manifest v3) — using Auth0 securely (Auth0 Community)](https://community.auth0.com/t/chrome-extension-manifest-v3-using-auth0-in-a-secure-manner/125433)
