# Agent Bridge 浏览器扩展

把当前网页的上下文一键发给本地网关,由内置 agent(摘要 / 简历匹配)分析后,结果直接以浮层面板显示在页面右上角。

## 工作流程

```
右键菜单 → content.js 抓取页面上下文 → background.js POST 到本地网关
        → 网关调用模型 → 返回结果 → 注入页面的 Shadow DOM 面板显示
```

网关地址固定为 `http://127.0.0.1:17321/tasks`(见 `background.js` 的 `GATEWAY_URL`)。**使用前必须先启动 gateway**(见仓库根目录与 `gateway/` 的说明)。

## 功能

- **两个右键菜单项**(页面任意处或选中文字后右键):
  - `Agent Bridge: 总结此页面` → `summary_page` agent
  - `Agent Bridge: 分析与简历匹配` → `job_match` agent(对比 `gateway/data/cv/cv.pdf`)
- **语言切换**:点扩展图标弹出 `popup`,可选 `跟随浏览器(默认)` / `中文` / `English`,偏好存在 `chrome.storage.sync`,每次请求实时生效。
- **结果面板**:Shadow DOM 隔离(不被页面 CSS 污染),渲染网关返回的、已净化的 Markdown→HTML,支持复制、关闭。

## 扩展采集 / 发送的数据

`content.js` 只发送**纯文本**,不发送图片像素、HTML、CSS、脚本:

| 字段 | 来源 | 说明 |
|---|---|---|
| `url` | `location.href` | 页面地址 |
| `title` | `document.title` | 标签页标题 |
| `selectedText` | `getSelection()` | 选中的文字(未选则为空) |
| `pageText` | `document.body.innerText` | 页面**可见文字**,空白压缩后截断到 20000 字符 |
| `imageText` | `img[alt]` / `img[title]` / `figcaption` / `[aria-label]` | **图片的文字线索**(去重、最多 40 条、截断到 4000 字符) |

`background.js` 再附加两个字段后 POST:
- `agent`:由点击的菜单项决定(`summary_page` / `job_match`)
- `lang`:由弹窗偏好解析得到(`跟随浏览器` → `zh`/`en`)

> 关于 `imageText`:这是"方案2"——不传图片本身,只抓图片的 alt/说明文字,让纯文本模型也能感知"页面上有哪些图、大致讲什么",零额外成本。若需要真正"看图/看图表",才需要截图 + vision 模型(尚未实现)。

## 文件

| 文件 | 作用 |
|---|---|
| `manifest.json` | MV3 清单;权限 `contextMenus / activeTab / scripting / notifications / storage`,`action` 弹窗,`host_permissions` 指向本地网关 |
| `background.js` | service worker:建右键菜单、解析语言、POST 网关、把结果注入页面面板 |
| `content.js` | 注入到页面,抓取上下文(含图片文字线索)并回传 |
| `popup.html` / `popup.js` | 扩展图标弹窗:语言偏好设置 |

## 安装(开发模式)

1. 打开 `chrome://extensions`
2. 打开右上角「开发者模式」
3. 点「加载已解压的扩展程序」,选择本 `extension/` 目录
4. 改动代码后,在该页点扩展卡片上的刷新图标重新加载

## 使用

1. 先启动网关:`cd gateway && uv run uvicorn app.main:app --host 127.0.0.1 --port 17321`
2. 打开任意网页(简历匹配请在招聘职位页),需要时选中文字
3. 右键 → 选 `总结此页面` 或 `分析与简历匹配`
4. 结果出现在页面右上角的浮层面板里

## 调试

- 扩展端日志:`chrome://extensions` → 本扩展 → 「Service Worker」→ Inspect,控制台有 `[Agent Bridge] ...` 日志(收到上下文、语言、网关响应状态等)。
- 网关端日志:运行 uvicorn 的终端,有 `[agent-bridge]` 行(收到任务、使用模型、`input=Xk` 输入字符数、耗时)。
- 请求历史:`gateway/data/tasks.jsonl`(每行一个任务,含 prompt、`input_chars`、`model`、耗时等)。

## 隐私

页面文本会发送到**你本机**的网关,再由网关转发给你在 `gateway/.env` 配置的模型服务(OpenAI / Moonshot / 火山方舟等)。`job_match` 会把简历全文一并发送。除此之外扩展不上传任何数据。
