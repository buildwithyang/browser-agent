# Agent Bridge Docker 部署（多租户云端）

用 Docker Compose 一键拉起三个服务：

| 服务 | 镜像 | 作用 |
| --- | --- | --- |
| `web` | nginx | 托管前端静态页 + 把 `/api/*` 反代到网关（对外唯一入口） |
| `gateway` | python + uv | FastAPI 网关，连 Postgres / Casdoor / 阿里云 OSS / LLM |
| `db` | postgres:16 | 数据库，首次启动用 `initdb/001-schema.sql` 自动建表 |

浏览器与扩展只跟 `web` 说话（对外统一端口 `http://<host>:17321`），网关与数据库都在 compose 内网，不直接对外暴露。
前端走同源 `/api`，由 nginx 反代到网关——和开发期 Vite 代理行为一致，没有跨站 cookie / CORS 问题。

## 前置条件

- 装好 Docker 与 Docker Compose（`docker compose version` 可用）。
- 一个 OpenAI 兼容的 LLM API Key。
- 一个 Casdoor 应用（登录用）。
- 一个阿里云 OSS bucket 及 AccessKey（简历存储用）。

## 步骤

### 1. 配置环境变量

```bash
cd deploy
cp .env.example .env
```

编辑 `.env`，**至少**填好：

- `POSTGRES_PASSWORD`：数据库密码。
- `AGENT_BRIDGE_MODELS`：LLM 分层路由 JSON（至少含一个 `default` 层的 `{url, key, model}`）。
- `AUTH_SESSION_SECRET`：换成随机长串，`openssl rand -hex 32`。
- `AUTH_FRONTEND_REDIRECT_URL` 与 `CASDOOR_REDIRECT_URI`：把里面的 `YOUR_HOST:17321` 换成用户实际访问 web 的地址（域名或 IP + `WEB_PORT`）。
- Casdoor：`CASDOOR_ENDPOINT` / `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET`。
- OSS：`ASSET_BASE_URL` / `OSS_BUCKET` / `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`（及 `OSS_REGION`）。

> 各变量含义见 `.env.example` 内注释。`.env` 含密钥，已被 `.gitignore` 忽略，不要提交。

### 2. 在 Casdoor 后台配回调地址

把 Casdoor 应用的 **Redirect URLs** 设为与 `.env` 里 `CASDOOR_REDIRECT_URI` **完全一致**，例如：

```
http://YOUR_HOST:17321/api/auth/callback
```

### 3. 启动

```bash
# 在 deploy/ 目录下
docker compose up -d --build
docker compose ps        # 三个服务应为 running / healthy
```

首次启动：db 为空 → 自动执行 `initdb/001-schema.sql` 建表；网关随后连库（`create_all` 因表已存在成为 no-op）。

### 4. 访问

浏览器打开 `http://<host>:17321`，点登录走完 Casdoor，回到简历管理页即成功。

## 常用运维命令

```bash
docker compose logs -f gateway      # 看网关日志
docker compose logs -f web          # 看 nginx 日志
docker compose ps                   # 服务状态
docker compose restart gateway      # 重启网关
docker compose down                 # 停并删容器（保留数据卷）
docker compose down -v              # 连数据卷一起删（清库，谨慎）
docker compose up -d --build        # 改代码后重建并更新
```

数据库数据在命名卷 `agent-bridge_pgdata`，`down` 不会丢；只有 `down -v` 才会清空。

## 故障排查

- **登录回跳报错 / redirect_uri 不匹配**：`CASDOOR_REDIRECT_URI` 必须和 Casdoor 后台、以及实际访问地址三者一致（含端口）。
- **登录后 cookie 不生效**：只跑 HTTP 时 `AUTH_COOKIE_SECURE` 必须是 `false`；上 HTTPS 后才改 `true`。
- **简历上传/解析失败**：检查 `STORAGE_PROVIDER=oss` 及 OSS 四个变量；`fake` 模式不会真正存储。
- **网关起不来 / 连不上库**：`docker compose logs gateway` 看错误；确认 `db` 已 healthy，`POSTGRES_PASSWORD` 与 `DATABASE_URL` 一致。

## 验证 checklist

```bash
docker compose exec db pg_isready
docker compose exec db psql -U agentbridge -d agentbridge -c '\dt'   # 应见 4 张表
curl -I  http://localhost:17321/                  # 200，返回前端 SPA
curl -i  http://localhost:17321/api/auth/login    # 302 跳转到 Casdoor
```

## 说明 / 后续

- **对外只有一个端口**：宿主机的 `17321` 映射到 web/nginx，是唯一入口；网关容器内部也叫 17321，但只在 compose 内网，不单独对外映射。SPA 在 `/`、API 在 `/api`（nginx 去掉 `/api` 前缀转发到 `gateway:17321`）。
- **浏览器扩展**：扩展默认连 `http://127.0.0.1:17321`（见 [INSTALL.zh-CN.md](INSTALL.zh-CN.md)），那是本地直连网关的老用法。要接入云端，需改扩展让它走 `http://<host>:17321/api`，并在网页登录后由扩展调 `POST /auth/extension-token` 取 bearer token——属扩展侧改动，不在本部署内。
- **HTTPS**：当前只跑 HTTP。上公网前请在前面加 TLS 终止（反代证书 / Caddy 等），并把 `AUTH_COOKIE_SECURE=true`、各 URL 改 `https://`。
- **构建架构**：在 Apple Silicon 上构建得到 arm64 镜像；若部署到 amd64 服务器，请在目标机构建，或用 `docker buildx build --platform linux/amd64`。
