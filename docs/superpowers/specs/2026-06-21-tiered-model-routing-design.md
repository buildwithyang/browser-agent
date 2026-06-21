# 分层模型路由（Tiered model routing）设计

日期：2026-06-21

## 背景与目标

现状：网关用一组扁平环境变量配置 LLM——`OPENAI_API_KEY` / `OPENAI_BASE_URL`
共享一个 endpoint，`AGENT_BRIDGE_MODEL`（短输入）与 `AGENT_BRIDGE_MODEL_LONG`
（长输入，超过 `AGENT_BRIDGE_ROUTE_THRESHOLD` 字符）只切换 **model id**，
两个模型必须走同一家厂商（同一 base_url / key）。

目标：按 prompt 长度把请求路由到 **任意数量** 的分层，每层是独立的
`{url, key, model}`，可指向不同厂商。最少只配一个 `default` 大模型兜底。

## 配置格式（单个 JSON 环境变量，干净替换旧变量）

新增 `AGENT_BRIDGE_MODELS`，值为 JSON 对象：键是该层能容纳的最大 prompt
**字符数**（正整数），或字符串 `"default"`（兜底层，无上限，**必填**）。

```bash
AGENT_BRIDGE_MODELS='{
  "6000":   {"url": "https://api.deepseek.com/v1", "key": "sk-...", "model": "deepseek-chat"},
  "31000":  {"url": "https://api.moonshot.ai/v1",  "key": "sk-...", "model": "moonshot-v1-32k"},
  "default":{"url": "https://api.moonshot.ai/v1",  "key": "sk-...", "model": "moonshot-v1-128k"}
}'
```

最小配置：`AGENT_BRIDGE_MODELS='{"default": {"url":"...","key":"...","model":"..."}}'`

**干净替换**：删除 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`AGENT_BRIDGE_MODEL`、
`AGENT_BRIDGE_MODEL_LONG`、`AGENT_BRIDGE_ROUTE_THRESHOLD`。

`modelInfo` 字段：`model` 必填（非空）；`url`、`key` 可空——为空时不传给
OpenAI client（沿用旧的「显式值优先，否则回退 SDK 默认」语义，例如本地 Ollama）。

## 路由规则

数字阈值升序排序；对长度为 L 的 prompt，选 **阈值 ≥ L 的最小那层**；
若 L 超过所有阈值（或只配了 default），用 `default`。

| prompt 字符数 | 选中层 | 例中 model |
|---|---|---|
| 2,000 | `6000` | deepseek-chat |
| 10,000 | `31000` | moonshot-v1-32k |
| 50,000 | `default` | moonshot-v1-128k |

## 组件与改动

### 新增 `app/agents/model_router.py`
- `ModelTier(frozen dataclass)`：`url: str`、`key: str`、`model: str`、
  `max_chars: int | None`（None = default 兜底层）。
- `ModelRouter`：
  - `__init__(default: ModelTier, tiers: list[ModelTier])`——校验 default
    无阈值；tiers 按 `max_chars` 升序。
  - `pick(prompt_len: int) -> ModelTier`——线性匹配「容得下的最小层」。
  - `default_model -> str`——兜底层 model id（给 service.py 记日志/指标用）。
  - `from_json(raw: str) -> ModelRouter`——解析校验：必须是对象、必须含
    `default`、阈值为正整数、每层有非空 `model`；非法配置抛 `ValueError`（信息清晰）。

### `app/config.py`
- 删除 `openai_api_key/openai_base_url/model/model_long/route_threshold_chars`。
- 新增字段 `model_router: ModelRouter`（`field(default_factory=...)` 给一个
  仅含 default 占位层 `model="gpt-4o-mini"` 的兜底 router，保证 `Settings()`
  直接构造与测试导入不报错）。
- `from_env`：读 `AGENT_BRIDGE_MODELS`；为空 → 占位兜底 router（缺 key，真正发
  请求时由 OpenAI client 报错，与今天缺 key 行为一致）；非空但非法 → 抛
  `ValueError`（只在用户显式设置该变量时触发，不影响不设它的测试）。

### `app/agents/base.py`
- `OpenAIChatAgent.__init__(self, router: ModelRouter | None = None, *,
  client: OpenAI | None = None, model: str | None = None)`。
  - 无 router 时由 `model`（默认 `DEFAULT_MODEL`）合成单层 default router——
    保留测试与简单场景的「固定单模型 + 注入 client」用法。
- 按 `(url, key)` 懒构建并缓存 per-tier client（同厂多层共用一个 client）；
  注入的 `client` 优先用于所有层（测试）。
- `pick_model(prompt) -> str`（保留，service.py 用它记 model）= `pick(...).model`。
- `complete(system, user, tier: ModelTier)`：用 tier 选 client 与 model。
- `run`：`tier = router.pick(len(prompt))` → `complete(system, prompt, tier)`。
- `DEFAULT_MODEL` 改为字面量 `"gpt-4o-mini"`（不再读已删除的 env）。

### `app/agents/job_match.py`
- `run` 与 base 对齐：用 `router.pick(len(prompt))` 选 tier 再 `complete`。

### `app/main.py`
- 删除 `api_key/base_url/model/model_long/route_threshold_chars` 入参，改为
  `_agent_opts = dict(router=settings.model_router)`。
- `TaskService(default_model=settings.model_router.default_model)`。

### `app/modules/task/service.py`
- 不变（继续用 `agent.pick_model(prompt)` 与 `default_model`）。

### `gateway/.env.example`
- 用 `AGENT_BRIDGE_MODELS` 一段（含注释与示例）替换旧 LLM 段。

## 测试

- 新增/重写 `tests/test_routing.py`：覆盖 `ModelRouter.pick`（多层边界、超上限走
  default、只配 default）、`from_json`（正常解析、缺 default 报错、非法 JSON/阈值
  报错）、`agent.pick_model` 经 router 生效、同厂多层共用 client。
- 更新引用 `settings.model` 的测试为 `settings.model_router.default_model`
  （`test_tasks_api.py`、`test_tasks_auth.py`）。
- `test_summary_page.py` / `test_job_match.py` 的 `client=...，model=...` 构造保持可用
  （无 router 走单层 default），`captured["model"]` 仍为传入 model。

## 取舍

- JSON-in-env vs 专用 JSON 文件：选前者，沿用「密钥都在 .env」的现状，零新概念；
  多行 JSON 编辑略繁但可接受。
- 兜底而非硬失败：`AGENT_BRIDGE_MODELS` 缺失时用占位 router 而非 import 期抛错，
  避免拖垮不需要模型的测试与子命令；只有显式配错才立刻报错。
