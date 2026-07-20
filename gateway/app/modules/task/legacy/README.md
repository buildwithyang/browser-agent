# Retired Task Transport

该目录只保留旧版精确 `POST /tasks` 的防御性 raw route。正常情况下，外层 `TaskProtocolMiddleware` 会在读取请求体、session、身份、路由和 Service 之前直接返回稳定 `426 Upgrade Required`。

`api.py` 不声明 Pydantic body，不访问 `TaskService`，仅在 middleware wiring 改变时返回同一个共享升级响应。旧 transport schema、adapter 和文档执行图均已删除；新代码禁止依赖该目录。
