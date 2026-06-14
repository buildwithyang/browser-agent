# Agent Bridge - Resume Module

简历模块负责：用户上传简历（OSS 预签名直传）、服务端回源解析 PDF 文本、按用户管理多份简历并选定「生效简历」供 `job_match` 使用。

核心设计原则（沿用 asset 模块的解耦思路）：
- DB 只存 `object_key` 与元数据，访问域名不入库，由 `ASSET_BASE_URL` 配置拼接。
- 写入走 Presigned PUT URL（客户端直传 OSS），不经网关中转大文件。
- `complete-upload` 时网关用 Presigned GET 回源下载，`pypdf` 解析文本入库；`job_match` 直接读库，不再每次解析。
- 存储实现可插拔（`fake` / `oss`），业务层不感知云厂商 SDK。
- 所有接口强制登录，数据严格按 `user_id` 隔离；`object_key` 必须落在 `resume/{user_id}/` 前缀下，杜绝越权。

## 上传流程

```text
1. POST /resumes/upload-url        -> 网关签发 OSS Presigned PUT URL + object_key
2. PUT <upload_url>（前端直传 OSS） -> 文件落到 OSS
3. POST /resumes/complete-upload   -> 网关回源下载、pypdf 解析文本入库，
                                      解析成功自动设为「生效简历」
```

## 接口

- `POST   /resumes/upload-url`：签发预签名上传地址（entity 固定为当前登录用户）。
- `POST   /resumes/complete-upload`：上传完成回调，下载解析并入库，返回简历详情。
- `GET    /resumes`：当前用户的简历列表（按创建时间倒序）。
- `POST   /resumes/{id}/activate`：把某份简历设为生效（仅解析成功的可生效）。
- `DELETE /resumes/{id}`：删除简历（库记录 + 尽力删除 OSS 对象）。

`parse_status`：`0` 待解析 / `1` 解析完成可用 / `2` 解析失败（`parse_error` 给出原因）。

## 配置（`.env`）

```env
STORAGE_PROVIDER=oss
OSS_REGION=cn-hangzhou
OSS_BUCKET=your-bucket
OSS_ACCESS_KEY_ID=your-ak
OSS_ACCESS_KEY_SECRET=your-sk
ASSET_BASE_URL=https://your-bucket.oss-cn-hangzhou.aliyuncs.com
RESUME_MAX_BYTES=10485760
DATABASE_URL=sqlite:///./data/agent_bridge.sqlite3
```

说明：
- `STORAGE_PROVIDER=fake` 时不真正存储、无法回源解析，仅用于跑通登录与接口联调。
- 真实解析需 `STORAGE_PROVIDER=oss` 并安装 OSS 依赖：`uv sync --extra oss`。
- `ASSET_BASE_URL` 可替换为 CDN 域名。

## 模块结构

```text
resume/
|- api.py        # FastAPI router（强制登录）
|- service.py    # object_key / 预签名 / 回源解析 / 生效简历编排
|- repo.py       # resume_resumes 读写
|- model.py      # ORM 映射
|- schema.py     # Pydantic schema
|- types.py      # StorageProvider 协议
|- providers.py  # fake / oss provider 与工厂
```

建表 SQL 以 `deploy/initdb/001-schema.sql` 的 `resume_resumes` 为权威，与 `model.py` 保持一致。
