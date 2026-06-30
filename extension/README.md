# Agent Bridge 浏览器扩展

把当前网页的上下文一键发给本地网关,由内置 agent(摘要 / 简历匹配)分析后,结果直接以浮层面板显示在页面右上角。

## 工作流程

```
右键菜单 → content.js 抓取页面上下文 → background.js POST 到本地网关
        → 网关调用模型 → 返回结果 → 注入页面的 Shadow DOM 面板显示
```

网关地址可在扩展弹窗(popup)配置,存于 `chrome.storage.local.gatewayUrl`,默认云端 `https://browser.buildwithyang.com/api`;自部署填本地 `http://127.0.0.1:17321`。默认值在 `auth.js` 的 `DEFAULT_GATEWAY` 单一维护,`background.js` 与 `popup.js` 共用。**自部署时使用前必须先启动 gateway**(见仓库根目录与 `gateway/` 的说明)。

登录态下,前端「浏览器扩展」卡片会经 `externally_connectable` 把 bearer token 推送给扩展,之后 `/tasks` 自动带 `Authorization: Bearer`。遇 401(token 过期/被解绑)扩展会清除本地 token 并提示在网页端重新连接。自部署(`REQUIRE_AUTH=false`)无需 token,匿名直连本地网关即可。

扩展逻辑测试:`cd extension && node --test`。

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
| `manifest.json` | MV3 清单;固定 `key`(定 ID)、`icons`、权限、`action` 弹窗、`host_permissions`、`externally_connectable` |
| `background.js` | service worker:建右键菜单、解析语言、POST 网关、把结果注入页面面板、收外部推送的 token |
| `content.js` | 注入到页面,抓取上下文(含图片文字线索)并回传 |
| `popup.html` / `popup.js` | 扩展图标弹窗:语言偏好 + 网关地址设置 |
| `auth.js` | token 存取、默认网关、鉴权头、外部消息处理(纯逻辑,带 `auth.test.js`) |
| `icons/` | `icon.svg` 主图 + `icon-16/32/48/128.png`(由 SVG 生成) |
| `package.sh` | 打 zip 的脚本(`npm run package`) |

## 安装

扩展 manifest 内置了固定 `key`,因此**所有人安装后扩展 ID 都一致**:
`cmajoaedbjinocbfdkebaedkdbkhbhai`。网页端据此推送登录 token,无需任何人再手动配 ID。

### 方式 A:Chrome 应用商店(推荐,所有用户)

1. 打开 [Chrome 应用商店页面](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai) 点「添加至 Chrome」。
2. 云端用户:打开网页端登录,在「浏览器扩展」卡片点「连接扩展」即可。
3. 自部署用户:点扩展图标,在 popup 把网关地址填成 `http://127.0.0.1:17321`(`REQUIRE_AUTH=false` 匿名直连,无需登录)。

### 方式 B:从源码加载(开发者 / 改源码)

打开 `chrome://extensions` → 右上角开「开发者模式」→ 点「加载已解压的扩展程序」→ 选本 `extension/` 目录。因 manifest 含固定 key,加载后的 ID 与商店版一致。改动后到 `chrome://extensions` 点扩展卡片的刷新图标重新加载。

## 打包

```bash
cd extension
npm run package        # 产出 dist/agent-bridge-extension-<版本>.zip
```

zip 用于上传 Chrome 应用商店发布更新(`Dashboard → Package → Upload new package`,需先在 `manifest.json`
递增 `version`)。打包只含运行所需文件,排除测试 / `package.json` / 本说明 / 私钥。
自部署 / 改源码无需打包,直接「方式 B」加载本 `extension/` 目录即可。

> 固定 ID 由 `manifest.json` 的 `key`(公钥)派生;对应私钥在 `extension/key.pem`,**不入库**
> (仅日后签 `.crx` 时才需要)。上架商店后若分配了不同 ID,需把新 `key` 回填到 `manifest.json`
> 与前端默认 ID([frontend/src/ExtensionCard.jsx](../frontend/src/ExtensionCard.jsx))。

## 使用

1. 先启动网关:在仓库根目录 `./dev-start backend`(仅网关)或 `./dev-start`(网关 + 前端)
2. 打开任意网页(简历匹配请在招聘职位页),需要时选中文字
3. 右键 → 选 `总结此页面` 或 `分析与简历匹配`
4. 结果出现在页面右上角的浮层面板里

## 调试

- 扩展端日志:`chrome://extensions` → 本扩展 → 「Service Worker」→ Inspect,控制台有 `[Agent Bridge] ...` 日志(收到上下文、语言、网关响应状态等)。
- 网关端日志:运行 uvicorn 的终端,有 `[agent-bridge]` 行(收到任务、使用模型、`input=Xk` 输入字符数、耗时)。
- 请求历史:`gateway/data/tasks.jsonl`(每行一个任务,含 prompt、`input_chars`、`model`、耗时等)。

## 隐私

页面文本会发送到**你本机**的网关,再由网关转发给你在 `gateway/.env` 配置的模型服务(OpenAI / Moonshot / 火山方舟等)。`job_match` 会把简历全文一并发送。除此之外扩展不上传任何数据。
