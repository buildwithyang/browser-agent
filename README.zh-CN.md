# Agent Bridge

[English](README.md) | 中文

把任何网页变成可执行的 AI 上下文。

> 📦 安装与配置请看 **[安装说明](deploy/INSTALL.zh-CN.md)**(含截图和环境变量配置)。

## 概述

Agent Bridge 是一个浏览器扩展 + 本地网关,让用户把当前正在浏览的内容发送给本地 AI Agent。

目标很简单:

```
阅读
  ↓
发送给 Agent
  ↓
得到结果
```

不需要:

- 复制
- 粘贴
- 切换窗口
- 重复提供上下文

## 问题

今天用户不断地在这些地方之间搬运信息:

- LinkedIn
- GitHub
- Jira
- Notion
- 技术文档
- ChatGPT
- Claude

典型的工作流:

```
阅读内容 → 复制 → 打开 ChatGPT → 粘贴 → 提问
```

或者:

```
阅读内容 → 复制 → 打开终端 → 粘贴 → 执行
```

重复且低效。

## 解决方案

Agent Bridge 让用户显式地把浏览器上下文发送给 AI Agent:

```
浏览器
  ↓
Agent Bridge
  ↓
本地网关
  ↓
Agent
  ↓
结果
  ↓
浏览器
```

浏览器成为上下文的来源,Agent 成为处理器。

## 核心原则

- Agent Bridge **不是**浏览器自动化工具。
- Agent Bridge **不是** Playwright 的替代品。
- Agent Bridge 是一个**上下文投递系统**。

由用户来决定:

> 这段内容有价值,发给 Agent。

这种显式信号,比持续监控网页更有价值。

## 使用场景

### LinkedIn 职位分析

当前页面:

```
Senior Golang Engineer / Remote / Dubai
```

用户:右键 → 发送给 Agent。

Agent 返回:职位摘要、简历匹配度、潜在风险、面试准备要点、建议薪资范围。

### GitHub Issue 分析

当前页面:

```
Fix OpenIM login timeout issue
```

用户:发送给 Agent。

Agent 返回:问题摘要、可能的根因、建议的实现方案。

### 技术文档

当前页面:

```
Quectel 5G License Guide
```

用户:发送给 Agent。

Agent 返回:关键实现步骤、风险、建议的开发任务。

### ChatGPT / Claude 对话

当前页面包含一份 AI 生成的方案。

用户:发送给 Agent。

Agent 返回:批判性评审、遗漏的考虑点、改进建议。

## MVP 范围

### 浏览器扩展

采集:URL、页面标题、选中文本、页面可见内容。

操作:发送给 Agent。

### 本地网关

接收浏览器上下文,暴露:

```
POST /analyze
```

请求体:

```json
{
  "url": "...",
  "title": "...",
  "selection": "...",
  "content": "..."
}
```

### 内置 Agent

MVP 使用内置的 LLM 后端,负责:分析、总结、提取、生成、执行命令。

## 路线图

### 阶段一

```
浏览器 → 内置 Agent → 结果弹层
```

验证需求。

### 阶段二

```
浏览器 → 网关 → Agent → 结果 → 回写当前网页
```

允许把结果插入到:ChatGPT、Claude、LinkedIn 私信、Jira 评论、任意网页输入框。

## 愿景

任何网页都可以变成一个 AI 任务:

```
任意网页 → 发送给 Agent → 分析 → 返回结果
```

不用复制粘贴,不用切换上下文,只有 上下文 → 行动。

## 本地 MVP

第一个实现包含:

- Chrome 扩展,显式采集页面并在页内展示结果
- Python FastAPI 网关,监听 `127.0.0.1:17321`
- 内置 `SimpleAgent`,基于 OpenAI 兼容模型(无需额外安装外部 Agent)
- JSONL 任务存储,位于 `gateway/data/tasks.jsonl`

### 快速开始

完整步骤(含截图和环境变量说明)见 **[安装说明](deploy/INSTALL.zh-CN.md)**,简要流程:

启动网关:

```bash
cd gateway
cp .env.example .env   # 填入 API Key 等配置
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

后端通过单个环境变量 `AGENT_BRIDGE_MODELS` 随意切换 —— 一个按 **prompt 长度** 路由的 JSON map:

- 键 = 该层能容纳的最大 prompt 字符数;`"default"` = 兜底层(无上限,必填)。
- 值 = `{url, key, model}`,不同长度区间可指向 **不同厂家**(短页面走便宜快的、大页面走长上下文)。无需 key 的端点(如本地 Ollama)`url`/`key` 可留空。
- 最小只配 `default`;按需再加数字层优化特定长度。示例见 [gateway/.env.example](gateway/.env.example)。

加载 Chrome 扩展:

1. 打开 `chrome://extensions`
2. 开启开发者模式
3. 点击「加载未打包的扩展程序」
4. 选择 `extension/` 目录

使用:

1. 打开一个网页
2. 需要的话选中文字
3. 右键
4. 在 Agent Bridge 子菜单中选择动作(`总结此页面` 或 `分析与简历匹配`)
5. 在页面弹出的浮层面板中查看结果

运行网关测试:

```bash
cd gateway
uv run pytest
```
