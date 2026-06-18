-- Agent Bridge Gateway —— PostgreSQL 部署的权威初始化脚本。
-- 必须与 gateway/app/modules/*/model.py 保持一致；改表先改 model.py，再同步这里。
-- 本地默认走 SQLite，由 SQLAlchemy 自动建表，无需执行本文件。

-- =====================================================================
-- auth：用户主表（OAuth 用户的稳定标识与基础资料）
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.auth_users (
    user_id          VARCHAR(32) PRIMARY KEY,                        -- 内部用户 ID（uuid hex）
    provider         VARCHAR(32) NOT NULL,                           -- OAuth provider，当前为 casdoor
    provider_subject VARCHAR(255) NOT NULL,                          -- provider 侧稳定 subject
    username         VARCHAR(128),                                   -- provider 用户名
    display_name     VARCHAR(255),                                   -- 展示名
    email            VARCHAR(255),                                   -- 邮箱（可空）
    avatar_url       VARCHAR(1024),                                  -- 头像 URL（可空）
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, -- 创建时间
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- (provider, provider_subject) 唯一：同一第三方账号只对应一个本地用户
CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_users_provider_subject
    ON public.auth_users (provider, provider_subject);

-- 邮箱查询索引
CREATE INDEX IF NOT EXISTS idx_auth_users_email
    ON public.auth_users (email);

-- =====================================================================
-- auth_tokens：扩展 bearer token（DB opaque，可吊销 / 可解绑设备）
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.auth_tokens (
    id            VARCHAR(32) PRIMARY KEY,                         -- token 记录 ID（uuid hex）
    user_id       VARCHAR(32) NOT NULL,                            -- 归属用户（auth_users.user_id）
    token_hash    VARCHAR(64) NOT NULL,                            -- sha256(明文 token) 十六进制
    label         VARCHAR(128),                                    -- 设备/来源标识
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 签发时间
    last_used_at  TIMESTAMPTZ,                                     -- 最近使用
    expires_at    TIMESTAMPTZ NOT NULL,                            -- 过期时间（签发 + TTL）
    revoked       BOOLEAN NOT NULL DEFAULT FALSE                   -- 是否已吊销
);

-- token 校验：按 hash 唯一定位
CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_tokens_token_hash
    ON public.auth_tokens (token_hash);

-- 按用户列出 token（解绑设备 UI）
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_created_at
    ON public.auth_tokens (user_id, created_at);

-- =====================================================================
-- resume：简历表（object_key + 元数据 + 解析文本 + 生效标记，按用户隔离）
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.resume_resumes (
    id                VARCHAR(32) PRIMARY KEY,                        -- 简历 ID（uuid hex）
    user_id           VARCHAR(32) NOT NULL,                          -- 归属用户（auth_users.user_id）
    object_key        TEXT NOT NULL UNIQUE,                          -- 对象存储路径 resume/{user_id}/{uuid}.pdf
    filename          VARCHAR(255),                                  -- 原始文件名
    content_type      VARCHAR(128),                                  -- MIME 类型
    file_size         BIGINT,                                        -- 文件大小（字节）
    etag              VARCHAR(128),                                  -- 对象存储返回的 ETag
    storage_provider  VARCHAR(32) NOT NULL,                          -- 存储后端类型（fake/oss）
    extracted_text    TEXT,                                          -- 解析出的简历纯文本（job_match 使用）
    text_chars        INTEGER NOT NULL DEFAULT 0,                    -- 解析文本字符数
    parse_status      SMALLINT NOT NULL DEFAULT 0,                   -- 0 待解析 / 1 完成可用 / 2 失败
    parse_error       VARCHAR(512),                                  -- 解析失败原因（可空）
    is_active         BOOLEAN NOT NULL DEFAULT FALSE,                -- 是否为该用户当前生效简历
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, -- 创建时间
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);

-- 按用户拉取简历列表（倒序分页）
CREATE INDEX IF NOT EXISTS idx_resume_user_created_at
    ON public.resume_resumes (user_id, created_at);

-- 快速定位某用户的生效简历
CREATE INDEX IF NOT EXISTS idx_resume_user_active
    ON public.resume_resumes (user_id, is_active);

-- =====================================================================
-- task：任务记录（metrics-only，刻意不存 prompt / 结果 / 页面正文 / URL）
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.task_records (
    id                VARCHAR(32) PRIMARY KEY,                        -- 任务 ID（uuid hex）
    user_id           VARCHAR(32),                                   -- 归属用户（匿名扩展调用为 NULL）
    agent             VARCHAR(32) NOT NULL,                          -- summary_page / job_match ...
    lang              VARCHAR(8)  NOT NULL DEFAULT 'auto',           -- 输出语言
    model             VARCHAR(128) NOT NULL DEFAULT '',              -- 实际路由到的模型
    status            VARCHAR(16) NOT NULL,                          -- completed / failed
    input_chars       INTEGER NOT NULL DEFAULT 0,                    -- prompt 字符数
    result_chars      INTEGER NOT NULL DEFAULT 0,                    -- 结果字符数
    duration_ms       INTEGER,                                       -- 耗时（毫秒）
    error             VARCHAR(512),                                  -- 失败原因（可空）
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP -- 创建时间
);

-- 按用户查用量（计费 / 限流基础）
CREATE INDEX IF NOT EXISTS idx_task_records_user_created_at
    ON public.task_records (user_id, created_at);

-- 全局按时间分页
CREATE INDEX IF NOT EXISTS idx_task_records_created_at
    ON public.task_records (created_at);

-- =====================================================================
-- 统一更新时间触发器：每次 UPDATE 自动刷新 updated_at
-- =====================================================================
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auth_users_set_updated_at ON public.auth_users;
CREATE TRIGGER trg_auth_users_set_updated_at
BEFORE UPDATE ON public.auth_users
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_resume_resumes_set_updated_at ON public.resume_resumes;
CREATE TRIGGER trg_resume_resumes_set_updated_at
BEFORE UPDATE ON public.resume_resumes
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();
