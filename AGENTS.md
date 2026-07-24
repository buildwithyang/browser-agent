# AGENTS.md

## Rules
- 回答保持简洁高效。
- 修改前先看相关模块的 `README.md`。
- 保持 `README.md` / `README.zh-CN.md` / `extension/README.md` 面向用户；工程约束放在这里。
- 面向云端、多租户
- 只有新的大 feature 开发才使用 superpowers 技能开发,局部代码优化不用使用此技能。
- 面向 Senior Developer.
  - 讨论设计的方案的时候，尽可能的使用设计模式，和用户沟通
  - 每个 Interface, Abstract, Function 增加注释，复杂的函数主体主流程增加适当的注释

## Architecture

- 网关代码在 `gateway/app/`，新代码遵守 `API -> Service -> Repository -> DB` 分层。
- `modules/<name>/api.py` 只做路由、参数、HTTP 错误映射；禁止直接访问 DB 或写核心业务。
- `modules/<name>/service.py` 只做业务编排；禁止写 HTTP 细节、手拼 SQL、跨模块直接调用别人的 `Repo`。
- `modules/<name>/repo.py` 只做持久化读写；禁止做业务决策或抛 `HTTPException`。
- `repo.py` 直接返回领域对象（各模块 `schema.py` 的 Pydantic schema）供 `service.py` / `api.py` 消费。
- model → 领域对象的转换写在 repo 的 `_to_data()`。
- `core/` 禁止依赖 `modules/`。
- 外部厂商适配代码（OSS、Casdoor）必须放在所属模块内（`resume/providers.py`、`auth/service.py`），业务层不感知厂商 SDK。
- 数据库结构必须兼容 `SQLite3` 和 `PostgreSQL`。
- 新增 / 修改表或列时，同步更新 `deploy/initdb/001-schema.sql`；该文件是 PostgreSQL 部署的唯一权威初始化脚本，必须和 `modules/*/model.py` 保持一致。
- `agents/` 是原有的浏览器任务执行层（summary_page / job_match），保持无状态：任何按用户区分的数据（简历文本）由调用方注入，不要在 agent 实例上缓存跨请求状态。
- 要保持架构合理，不要为了简单的功能牺牲架构的简洁性，合理性。

## Layout

```text
gateway/app/
|- main.py            # FastAPI 入口：session 中间件、lifespan 装配、路由挂载（纯装配）
|- config.py          # Settings：从环境 / .env 读取（OpenAI / DB / Casdoor / OSS / session）
|- render.py          # Markdown -> 安全 HTML
|- core/              # 跨模块基础设施，禁止依赖 modules/
|  |- db.py           # Base / DatabaseResources / create / close（SQLite + PostgreSQL）
|  |- session.py      # 签名 cookie session 中间件
|  |- sql_types.py    # UUIDHexString 等自定义列类型
|- modules/
|  |- auth/           # Casdoor OAuth2 + PKCE 登录，登录态存签名 session cookie
|  |- resume/         # 简历：OSS 预签名直传 + 服务端 PDF 解析 + 按用户管理
|  |- task/           # 协议 gate、Quick Insight、Workspace reducer、指标落库
|- agents/            # summary_page / job_match 任务执行层，被 modules/task 编排

frontend/               # 独立 React (Vite) 简历管理前端
deploy/initdb/          # PostgreSQL 权威建表脚本
```

说明：`agents/` 不是 `modules/`，是被 `modules/task` 调用的执行层；它依赖 `modules/task/schema`
（`QuickInsightRequest`、`WorkspaceRequest`、`ChatResult` 等 Agent 契约）。因此 `modules/task/__init__.py` 保持轻量，
不要在包初始化里 import `service`（会反向依赖 `agents` 造成循环）。

## Commands

- 安装依赖：`cd gateway && uv sync`（PostgreSQL 部署需 `uv sync --extra postgres`）
- 全部测试：`cd gateway && uv run pytest`
- 指定测试：`cd gateway && uv run pytest tests/test_job_match.py`
- 导入检查：`cd gateway && uv run python -c "import app.main; print('main import ok')"`
- 前端（简历管理页）：`cd frontend && npm install && npm run dev`

## Constraints

- 不要把密钥、token、完整外部响应中的敏感字段写进日志（OpenAI / Casdoor / OSS key 一律不落日志）。
- 简历原文、页面正文、完整 prompt 属于用户隐私：持久化时优先脱敏，默认只长期保留运营指标（字符数、模型、耗时）。
- 表结构默认值要同时兼容 `SQLite` 和 `PostgreSQL`。
- 新模块在写代码的同时补一份模块 `README.md`。
