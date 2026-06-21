# Agent Bridge 安装说明

整个安装分两步:先配置并启动本地 Gateway,再在 Chrome 中加载扩展。

## 前置条件

- Chrome 浏览器
- [uv](https://docs.astral.sh/uv/)(Python 包管理器,用于运行 Gateway)
- 一个 OpenAI 或任意 OpenAI 兼容服务的 API Key(Moonshot / 豆包 / DeepSeek / 本地 Ollama 均可)

## 第一步:配置环境变量

进入 `gateway` 目录,复制示例配置并填入真实值:

```bash
cd gateway
cp .env.example .env
```

编辑 `.env` 文件,各变量含义如下:

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `AGENT_BRIDGE_MODELS` | ✅ | LLM 分层路由,一个 JSON map。键 = 该层能容纳的最大 prompt 字符数;`"default"` = 兜底层(无上限,必填)。值 = `{url, key, model}`,每层独立、可跨厂。按 prompt 长度选「阈值 ≥ 长度 的最小那层」,超出所有阈值用 `default`。阈值单位是**字符**(中文约 1 字符 = 1 token,英文约 4 字符 = 1 token,中文偏多时阈值要设低)。无需 key 的端点(如本地 Ollama)`url`/`key` 可留空。常见 url:`https://api.moonshot.ai/v1`(Moonshot)、`https://ark.cn-beijing.volces.com/api/v3`(火山方舟)、`https://api.deepseek.com/v1`(DeepSeek)、`http://localhost:11434/v1`(本地 Ollama) |
| `AGENT_BRIDGE_CV_PATH` | | 简历文件路径(职位匹配 Agent 使用),默认 `data/cv/cv.pdf`(相对 `gateway` 目录) |

> 注意:`.env` 包含密钥,不要提交到 git。真实环境变量优先于 `.env` 文件中的值,所以也可以不用 `.env`,直接 `export AGENT_BRIDGE_MODELS='...'`。

最简配置(单厂、只兜底):

```bash
AGENT_BRIDGE_MODELS='{"default": {"url": "https://api.moonshot.ai/v1", "key": "sk-...", "model": "moonshot-v1-128k"}}'
```

分层示例(短输入走便宜快的,长输入走大上下文,可跨厂):

```bash
AGENT_BRIDGE_MODELS='{
  "6000":   {"url": "https://api.deepseek.com/v1", "key": "sk-deepseek-xxx", "model": "deepseek-chat"},
  "31000":  {"url": "https://api.moonshot.ai/v1",  "key": "sk-moonshot-xxx", "model": "moonshot-v1-32k"},
  "default":{"url": "https://api.moonshot.ai/v1",  "key": "sk-moonshot-xxx", "model": "moonshot-v1-128k"}
}'
```

## 第二步:启动 Gateway

```bash
cd gateway
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

扩展固定访问 `http://127.0.0.1:17321`,端口不要改。

## 第三步:在 Chrome 中安装扩展

扩展有固定 ID(`njllhjolgnfainjapjekgimjbipigpja`)。两种安装来源任选其一:

- **应用商店**(最省事,上架后补链接):点「添加至 Chrome」即可,可跳过下面的开发者模式步骤。
- **离线 zip / 源码目录**(本文档场景):用下面的「加载已解压」方式。zip 由 `cd extension && npm run package` 生成后解压;没有 zip 时直接选仓库里的 `extension` 目录也行。

### 1. 打开扩展程序管理页

点击 Chrome 右上角菜单 → 扩展程序 → 管理扩展程序(或直接在地址栏输入 `chrome://extensions`):

![打开扩展程序管理页](install_extension_cn_1.png)

### 2. 加载未打包的扩展程序

先打开右上角的「开发者模式」开关,然后点击左上角的「加载未打包的扩展程序」:

![加载未打包的扩展程序](install_extension_cn_2.png)

### 3. 选择扩展目录

在弹出的文件选择框中,选择**解压后的扩展目录**(或没打包时直接选本项目下的 `extension` 目录):

![选择 extension 目录](install_extension_cn_3.png)

安装完成后,扩展列表中会出现 **Agent Bridge**。

> 加载未打包的扩展是持久的,Chrome 重启后依然存在,不需要重复安装。如果更新了扩展源码,到 `chrome://extensions` 点一下 Agent Bridge 卡片上的刷新按钮(⟳)即可生效。

## 使用方法

1. 打开任意网页(需要的话先选中一段文字)
2. 右键 → 在 **Agent Bridge** 子菜单中选择一个动作,例如「总结此页面」或「分析与简历匹配」:

![右键菜单选择 Agent Bridge 动作](install_extension_cn_4.png)

3. 页面右侧会弹出 Agent Bridge 浮层面板,显示分析结果。以 LinkedIn 职位页为例,「分析与简历匹配」会给出总体结论、匹配评分、匹配优势、欠缺/风险和建议:

![浮层面板中的简历匹配分析结果](install_extension_cn_5.png)

## 常见问题

- **右键发送后没有反应 / 报错**:确认 Gateway 已启动,且监听在 `127.0.0.1:17321`。
- **返回模型调用错误**:检查 `AGENT_BRIDGE_MODELS` 中各层的 `url` / `key` 是否正确,`model` 是否是该服务商支持的。
- **大页面 / 长文本失败**:给 `default` 层用长上下文模型,或加一个更高阈值的层(必要时调低各层阈值,让大输入更早路由到长上下文模型)。
