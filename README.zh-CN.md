# Agent Bridge

[English](README.md) | 中文

把 LinkedIn、Indeed 岗位页面直接变成一份定制化求职申请。

> 📦 安装、截图与环境变量配置请看 [安装说明](deploy/INSTALL.zh-CN.md)。

## 大愿景（Vision）

**尊重用户的注意力，让 AI 成为工作流的一部分。**

我们相信，未来很长一段时间，人类仍然需要通过浏览器获取信息。当用户阅读一篇文章、查看一个岗位、浏览一个 GitHub Issue、阅读一封邮件时，Agent Bridge 能够理解用户当前关注的内容，并立即提供帮助。

AI 不再只是回答问题。AI 将真正把算力应用到用户关注的地方。

## 小愿景（Mission）

**从解决一个小需求开始：帮助用户阅读并匹配 JD。**

我们不会一开始就做一个万能 Agent，而是先完成一个真实、完整、每天都会发生的求职工作流：

```text
浏览 LinkedIn / Indeed 岗位并右键
  ↓
分析岗位与简历匹配度
  ↓
生成定制化 CV
  ↓
生成 Cover Letter
  ↓
记录投递
  ↓
模拟面试
  ↓
Offer
```

近期目标很明确：让 AI 真正帮助用户拿到第一份 Offer。当这条工作流跑通之后，再逐步扩展到更多浏览器场景。

## Agent Bridge 做什么

Agent Bridge 由 Chrome 扩展、网关和 AI Agent 组成。用户在 LinkedIn、Indeed 等招聘网站查看岗位时，可以明确地把当前 JD 交给 Agent：

```text
LinkedIn / Indeed 岗位页面
  ↓ 右键
Agent Bridge
  ↓
岗位 JD + 用户当前生效的 CV
  ↓
岗位匹配分析 + 定制化申请材料
  ↓
直接在当前页面展示结果
```

不用复制粘贴，不用在岗位页面和聊天工具之间来回切换。当前页面就是上下文，Agent 负责把上下文变成行动。

## 当前能力

- 采集当前岗位页面的 URL、标题、选中文本和可见正文。
- 将 LinkedIn、Indeed 岗位 JD 与用户当前生效的 CV 对比。
- 解释公司业务、目标市场和岗位职责。
- 根据岗位核心要求给出克制、真实的匹配分。
- 逐项展示已匹配、部分匹配和缺失的技能及依据。
- 用户确认岗位值得投递后，按需生成定制化 Cover Letter。
- 给出具体 CV 修改建议，包括 ATS 关键词、内容前置和成果量化改写。
- 在面向云端、多租户的网页端管理多份 CV，并选择当前生效版本。
- 在当前岗位页面内直接展示结果。

> 定制化 CV 文件生成、投递记录和模拟面试属于产品方向，目前还没有形成完整的端到端能力。

## 使用流程

1. 在网页端上传一份或多份 CV，并选择当前生效的 CV。
2. 打开 LinkedIn、Indeed 或其他招聘网站的岗位详情页。
3. 右键选择 **分析与简历匹配**。
4. 查看匹配结论、业务介绍和逐项技能匹配。
5. 判断岗位值得投递后，点击 **生成求职信**。
6. 使用生成的 Cover Letter 和 CV 修改建议准备申请材料。

系统会先生成岗位匹配分析；只有用户明确需要时，才继续生成 Cover Letter 和 CV 建议，避免在不合适的岗位上浪费时间与模型调用。

## 产品原则

- **尊重用户注意力：** 由用户决定哪一个页面值得 AI 介入。
- **工作流优先：** 结果直接出现在工作发生的页面，而不是停留在聊天窗口。
- **真实匹配：** 核心要求缺失就应降低评分，不给安慰分。
- **用户数据隔离：** CV 和申请数据始终按登录用户隔离。
- **隐私优先：** 页面正文、CV 原文和完整 Prompt 都属于敏感数据；长期存储默认优先保留运营指标，而不是原文。
- **模型可替换：** 网关支持 OpenAI 兼容模型，并可按 Prompt 长度路由到不同模型。

## 架构

```text
Chrome 扩展
  ↓
FastAPI 网关
  ├─ 登录与会话
  ├─ CV 管理
  ├─ 任务编排
  └─ 岗位匹配 Agent
       ↓
OpenAI 兼容模型
```

项目面向云端、多租户设计。网关遵循 API、Service、Repository、DB 分层；岗位 Agent 保持无状态，每次请求由调用方注入当前用户的 CV，避免跨用户缓存数据。

## 本地开发

完整配置见 [安装说明](deploy/INSTALL.zh-CN.md)。

启动网关：

```bash
cd gateway
cp .env.example .env
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

模型通过 `AGENT_BRIDGE_MODELS` 配置。它是一个按 Prompt 长度路由的 JSON Map，最小配置只需要 `default` 模型，示例见 [gateway/.env.example](gateway/.env.example)。

扩展可以从 [Chrome 应用商店](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai)安装，也可以在 `chrome://extensions` 开启开发者模式后加载 `extension/` 目录。

运行网关测试：

```bash
cd gateway
uv run pytest
```

运行扩展测试：

```bash
cd extension
npm test
```

## 路线图

### 现在：读懂并匹配岗位

- LinkedIn / Indeed 岗位页面采集
- CV 与 JD 匹配分析
- 公司业务与岗位介绍
- 技能差距与真实评分
- 按需生成 Cover Letter 和 CV 修改建议

### 下一步：完成投递

- 基于用户真实经历生成定制化 CV
- 收藏岗位并记录投递进度
- 关联保存每次投递使用的 CV 和 Cover Letter

### 之后：赢得 Offer

- 根据 JD 和用户 CV 生成面试问题
- 模拟面试与反馈
- 跟进提醒和申请阶段辅助

