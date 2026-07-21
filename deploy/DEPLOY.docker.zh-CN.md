# Agent Bridge Docker 部署（多租户云端）

Docker Compose 启动三个服务：

| 服务 | 镜像 | 作用 |
| --- | --- | --- |
| `web` | nginx | 托管前端，并把 `/api/*` 反代到 Gateway |
| `gateway` | python + uv | FastAPI、Casdoor、OSS、PostgreSQL 与 Agent 编排 |
| `db` | postgres:16 | 首次启动时执行 `initdb/001-schema.sql` |

本指南的 Extension 接入部分只描述 Agent Bridge 官方云端部署。Compose 本身可以把
web/frontend/API 部署到自定义 `http://<host>:17321`，Gateway 和 PostgreSQL 仍只在
Compose 内网可见，前端通过同源 `/api` 访问 Gateway。

当前 Extension 的 Gateway 目标不可由用户配置：商店包和 production ZIP 只访问
`https://browser.buildwithyang.com/api`，源码 development build 只访问
`http://127.0.0.1:17321`；`manifest.json` 的 host permissions 也只允许这两个 host。
因此，通用自定义 host Docker 部署目前只能作为 web/frontend/API 部署使用，不是受支持
的 Extension 目标。

## 前置条件

- Docker 与 Docker Compose（`docker compose version` 可用）。
- 支持 OpenAI-compatible Chat Completions 的模型服务和 API Key。
- Casdoor 应用。
- 阿里云 OSS bucket 与 AccessKey。

Workspace 使用 Chat Completions streaming 和 protocol v4 NDJSON，不使用 Responses API。
自定义模型代理必须兼容 `chat.completions.create(..., stream=True)`。

## 1. 配置环境变量

```bash
cd deploy
cp .env.example .env
```

至少配置：

- `POSTGRES_PASSWORD`。
- `AGENT_BRIDGE_MODELS`：至少包含 `default` 层的 `{url, key, model}`。
- `AUTH_SESSION_SECRET`：使用 `openssl rand -hex 32` 生成随机值。
- `AUTH_FRONTEND_REDIRECT_URL` 与 `CASDOOR_REDIRECT_URI`：把
  `YOUR_HOST:17321` 换成真实域名或 IP 与 `WEB_PORT`。
- `CASDOOR_ENDPOINT` / `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET`。
- `ASSET_BASE_URL` / `OSS_BUCKET` / `OSS_ACCESS_KEY_ID` /
  `OSS_ACCESS_KEY_SECRET`，以及需要时的 `OSS_REGION`。

变量说明见 `.env.example`。`.env` 含密钥并已被 `.gitignore` 忽略，不要提交。

## 2. 配置 Casdoor 回调

Casdoor 应用的 **Redirect URLs** 必须与 `CASDOOR_REDIRECT_URI` 完全相同，例如：

```text
http://YOUR_HOST:17321/api/auth/callback
```

## 3. 启动

```bash
docker compose up -d --build
docker compose ps
```

首次启动时，空数据库会执行 `initdb/001-schema.sql`；Gateway 随后连接 PostgreSQL。
三个服务应显示 running / healthy。

## 4. 访问与扩展

自定义 host 部署可由普通浏览器打开 `http://<host>:17321`，完成 Casdoor 登录并验证
web/frontend/API；这不会让当前 Extension 连接到该 host。

官方云端用户从 [Chrome 应用商店](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai)
安装扩展；商店包和仓库生成的 production ZIP 固定访问
`https://browser.buildwithyang.com/api`。从源码加载的 development build 固定访问
`http://127.0.0.1:17321`，仅用于本机开发。

当前仓库没有手动 Gateway 配置或面向任意 host 的打包能力。不要把官方商店包或
production ZIP 描述为可连接通用自定义 host；若部署目标不是官方云端，本指南只覆盖
其 web/frontend/API，不覆盖 Extension 接入。

Extension 与 Gateway 必须都支持 protocol v4。旧扩展访问 Task 接口会收到
`426 Upgrade Required`；此时更新扩展，不要尝试绕过 protocol Header。

## Workspace streaming 反代边界

Quick Insight 是普通 JSON。`POST /api/tasks/workspace` 返回
`application/x-ndjson`，普通 reply 的 Markdown 会增量到达；CV 和 Cover Letter 只发送
生成状态，并在 `completed` 终态返回完整 Attachment。

`nginx.conf` 使用精确 location 覆盖 Workspace 路径：

```nginx
location = /api/tasks/workspace {
    proxy_pass http://gateway:17321/tasks/workspace;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

这个 exact location 的优先级高于通用 `/api/` 前缀 location，且 `proxy_pass` 显式映射到
Gateway 的 `/tasks/workspace`。不要删除 `proxy_buffering off` 或 `proxy_cache off`；否则
Nginx 可能聚合 delta，用户直到终态才看到回复。Gateway 也返回
`X-Accel-Buffering: no`，两层配置共同保证 streaming boundary。

其他 `/api/*` 继续使用原有 `location /api/`，由带尾部 `/` 的 `proxy_pass` 去掉 `/api`
前缀。例如 `/api/auth/login` 转发为 `http://gateway:17321/auth/login`。

## 常用运维命令

```bash
docker compose logs -f gateway
docker compose logs -f web
docker compose ps
docker compose restart gateway
docker compose down
docker compose down -v
docker compose up -d --build
```

数据库数据位于命名卷 `agent-bridge_pgdata`。`down` 保留数据；`down -v` 会删除数据卷，
只能在确认需要清库时使用。

## 故障排查

- **Workspace 回复直到最后才出现**：确认请求命中精确
  `/api/tasks/workspace`，并检查 `proxy_buffering off` / `proxy_cache off` 没有被上层反代
  覆盖。
- **提示更新扩展 / HTTP 426**：安装最新扩展；Gateway 只接受
  `X-Agent-Bridge-Protocol-Version: 4`。
- **Workspace 失败后没有历史**：这是原子状态边界；只有 `completed.response` 会写入
  canonical histories / artifacts。先检查 Gateway 的安全错误码与模型代理 streaming 兼容性。
- **登录回跳或 `redirect_uri` 不匹配**：Casdoor、`.env` 和真实访问地址必须完全一致。
- **HTTP 登录后 cookie 不生效**：HTTP 部署使用 `AUTH_COOKIE_SECURE=false`；TLS 部署改为
  `true`。
- **简历上传/解析失败**：检查 `STORAGE_PROVIDER=oss` 与 OSS 配置；`fake` 不会真实存储。
- **Gateway 无法启动或连接数据库**：检查 `docker compose logs gateway`、db health、
  `POSTGRES_PASSWORD` 与 `DATABASE_URL`。

日志不得包含页面正文、完整 prompt、模型响应、bearer token、Casdoor/OSS/模型 key。

## 验证 checklist

```bash
docker compose exec db pg_isready
docker compose exec db psql -U agentbridge -d agentbridge -c '\dt'
curl -I http://localhost:17321/
curl -i http://localhost:17321/api/auth/login
docker compose exec web nginx -T
```

应确认：数据库 ready 且存在初始化表；SPA 返回 200；登录入口返回 Casdoor redirect；
`nginx -T` 中 exact Workspace location 包含两个 off 指令和全部 forwarding headers。

官方云端的真实 streaming 验收需要加载最新扩展，在 LinkedIn 或 Indeed 岗位页验证：普通 reply
在 `completed` 前更新、Artifact 只显示状态、成功终态刷新后仍存在、失败恢复输入且不增加
history。不要用伪造日志代替浏览器验收。

## 部署说明

- 对外唯一端口仍是 web/nginx 的 `17321`；不要直接暴露 Gateway 或 PostgreSQL。
- 公网部署应在前方增加 TLS 终止，并把相关 URL 与 `AUTH_COOKIE_SECURE` 改为 HTTPS 配置。
- Apple Silicon 默认构建 arm64 镜像；amd64 服务器应在目标机构建，或使用
  `docker buildx build --platform linux/amd64`。
