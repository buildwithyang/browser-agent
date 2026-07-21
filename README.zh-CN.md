# Agent Bridge

[English](README.md) | 中文

把 LinkedIn、Indeed 岗位页面直接变成一份定制化求职申请。

> 📦 安装、截图与环境变量配置请看 [安装说明](deploy/INSTALL.zh-CN.md)。

> 下文 Shared Workspace 已在当前源码中实现；云端网关部署和 Chrome 应用商店发布仍是两个独立的上线步骤。

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

Agent Bridge 由 Chrome 扩展、网关和 AI Agent 组成。浏览器先给出聚焦的 **Quick Insight**，用户选择可编辑的 Prompt Shortcut 后进入持久的 Side Panel，在不重复页面上下文的情况下继续完成任务：

```text
LinkedIn / Indeed 岗位页面
  ↓ 右键
Quick Insight
  ↓ 选择 Prompt Shortcut
Side Panel 共享 Workspace
  ↓
当前页面 + 生效 CV + 共享历史
  ↓
分析、定制简历或 Cover Letter
```

不用复制粘贴，不用在岗位页面和聊天工具之间来回切换。当前页面就是上下文，Agent 负责把上下文变成行动。

## 当前能力

- 任意网页先显示 Quick Insight；LinkedIn / Indeed 在选中完整 JD 时显示岗位匹配洞察，普通网页显示摘要。
- 对比岗位 JD 与当前生效 CV，展示业务与岗位重点、最大优势和最大差距。
- 岗位页提供 **Analyze**、**Tailor Resume**、**Generate Cover Letter**、**Ask More** 四个可编辑 Prompt Shortcut；普通网页只提供 **Ask More**。
- 点击 Shortcut 只会把本地化 Prompt 填入 Workspace，不会自动发送，用户可以先检查或修改。
- 同一页面的所有 Shortcut 进入一个 Side Panel Workspace，共享一份按时间排列的历史，CV 与 Cover Letter 作为生成它们的 Assistant Message 的 Attachment 展示。
- 按“登录用户 + 规范化网页资源”在当前 Chrome 配置中恢复 Workspace。
- 每一轮都由 Agent 根据用户最终发送的消息、共享历史与当前 Artifact 重新规划；Shortcut ID 不会作为路由指令发送。
- 基于共享上下文持续修改简历或 Cover Letter，并在时间线中保留此前的产物版本。
- 在面向云端、多租户的网页端管理多份 CV，并选择当前生效版本。
- Context Routing 和网页资源归一化都由网关负责，新增路由规则不需要重新发布扩展。
- 在应用响应前检查扩展与网关协议；不兼容时提供更新入口，不清空登录态或当前 Workspace。

Workspace 历史以及最新 CV / Cover Letter state 只保存在当前 Chrome 配置中，不建立服务端 Thread 或 Artifact。pure protocol v4 只保存完整的 User/Assistant pair，最多支持 10 次用户发送和 20 条消息；旧的本地 Workspace schema 会直接丢弃并创建全新 Workspace。达到上限后输入框、Shortcut 与发送按钮会禁用，但仍可阅读完整历史并复制已生成内容。

## 使用流程

1. 在网页端上传一份或多份 CV，并选择当前生效的 CV。
2. 打开任意网页；如需匹配 LinkedIn / Indeed 岗位，先选中完整 JD。
3. 右键选择 **Browser Agent**。
4. 阅读 Quick Insight，并选择一个 Prompt Shortcut。它只把本地化 Prompt 填入 Side Panel，不会自动发送。
5. 检查或修改草稿后再发送。Agent 根据最终消息、当前 Artifact 与共享历史判断是普通回复还是正式产物。
6. 在原消息中查看生成的 Attachment。Cover Letter 可直接复制；CV 当前打开网关提供的固定测试预览，真实私有版本化预览仍在路线图中。

Quick Insight 先回答“我应该知道什么”，Workspace 再回答“下一步应该做什么”，用户不需要从一个空白聊天框开始。

## 产品原则

- **尊重用户注意力：** 由用户决定哪一个页面值得 AI 介入。
- **工作流优先：** 结果直接出现在工作发生的页面，而不是停留在聊天窗口。
- **一个资源，一个 Workspace：** 同一登录用户在同一规范化网页上的 Prompt Shortcut 共享一份本地历史。
- **意图优先：** Shortcut 只准备可编辑草稿，用户最终发送的消息决定返回建议还是正式 Artifact。
- **真实匹配：** 核心要求缺失就应降低评分，不给安慰分。
- **用户数据隔离：** CV 和申请数据始终按登录用户隔离。
- **明确数据边界：** 页面正文、CV 原文和完整 Prompt 都属于敏感数据。当前内部用户阶段会持久化任务明细用于调试；面向公开用户上线前必须补齐脱敏、访问权限和保留周期策略。
- **模型可替换：** 网关支持 OpenAI 兼容模型，并可按 Prompt 长度路由到不同模型。

## 架构

```text
Chrome 扩展
  ├─ Quick Insight 浮层
  ├─ Side Panel Workspace
  └─ 按用户与资源隔离的本地状态
       ↓
FastAPI 网关
  ├─ 登录与会话
  ├─ CV 管理
  ├─ Context Router 与资源 URL 归一化
  ├─ 无状态 Workspace reducer
  └─ Job Match Orchestrator 与专业子 Agent
       ↓
OpenAI 兼容模型
```

项目面向云端、多租户设计。网关遵循 API、Service、Repository、DB 分层；Agent 保持无状态，每次请求携带页面上下文、共享历史、当前 Artifacts，并注入当前用户的 CV。`JobMatchAgent` 统一编排岗位分析、简历、求职信与开放问答四个专业子 Agent。公开的 Quick Insight 与 Workspace 接口不暴露 Agent 选择器，路由由后端负责。

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
- 多个 Prompt Shortcut 共享 Side Panel 历史
- 根据真实意图回答、生成或修改简历与 Cover Letter
- 在聊天时间线中保留 Cover Letter 历史 Attachment

### 下一步：完成投递

- 把固定 CV 测试预览替换为私有、版本化的真实 CV 托管
- 收藏岗位并记录投递进度
- 关联保存每次投递使用的 CV 和 Cover Letter

### 之后：赢得 Offer

- 根据 JD 和用户 CV 生成面试问题
- 模拟面试与反馈
- 跟进提醒和申请阶段辅助
