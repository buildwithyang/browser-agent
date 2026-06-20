# Agent Bridge 网关镜像（FastAPI + uv）。构建上下文 = 仓库根。
#   docker compose -f deploy/docker-compose.yml build gateway
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# 用官方 uv 镜像里的静态二进制，避免在镜像内 pip 安装 uv。
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv

WORKDIR /app

# 先只拷依赖清单，命中 Docker 层缓存：源码变更不会触发重新装依赖。
# --no-install-project：本项目无 build-system，不是可安装包，只装依赖即可。
# --extra postgres：装 psycopg[binary] / psycopg-pool（PostgreSQL 必需）。
COPY gateway/pyproject.toml gateway/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra postgres

# 再拷源码。app 作为子目录，cwd=/app 时 `app.main` 可被导入
# （与 pytest 的 pythonpath=["."] 一致）。
COPY gateway/app ./app

EXPOSE 17321

# 直接用 venv 里的 uvicorn，运行时不再触碰 uv / 不再联网解析。
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "17321"]
