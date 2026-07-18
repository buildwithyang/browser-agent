# Task Legacy Transport

该目录只兼容旧版 `POST /tasks` HTTP 协议，供 Chrome 扩展审核迁移期使用。

- `schema.py`：旧 wire format，类型统一使用 `Legacy` 前缀。
- `adapter.py`：旧请求转换为 `QuickInsightRequest` / `TaskRequest`，再把新响应转换回旧格式。
- `api.py`：deprecated `/tasks` 路由、身份解析和错误映射。

这里禁止复制 Agent、Service、Repository 或模型调用逻辑。兼容入口必须调用新的 `TaskService`；新代码也禁止依赖 `legacy/`。
