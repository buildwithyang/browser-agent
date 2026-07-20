# Retired Task Transport

该目录只保留旧版精确 `POST /tasks` 的防御性 raw route。它不是兼容生成接口；无论请求
是否携带协议 Header，外层 `TaskProtocolMiddleware` 都会在读取 request body、Session、
身份、路由和 Service 之前直接返回协议版本 2 的稳定 `426 Upgrade Required`。

`api.py` 不声明 Pydantic body、不访问 `TaskService`，仅在 middleware wiring 变化时返回
同一个共享升级响应。旧 transport schema、adapter、Agent 与 DocumentContent 执行图均已
删除；新代码禁止依赖该目录。
