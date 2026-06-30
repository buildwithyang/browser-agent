# 扩展 ↔ 网关 数据契约（Extension Contract）

> 本文是「扩展能渲染什么」的**唯一事实来源**,与具体功能无关。新增功能前先读这里,判断改动是
> **纯后端**(不动扩展、不重新发版上架)还是**触及契约边界**(必须改扩展并重新发 Chrome 商店版)。

## 1. 设计意图:扩展是「哑壳」

[extension/background.js](../extension/background.js) 被刻意做成一个**通用渲染器(哑壳)**:它对内容本身
一无所知,只照网关响应里的固定字段渲染面板。**所有内容与结构都由网关决定**。

这一设计目标在 [job_match 按需分块设计 spec](superpowers/specs/2026-06-23-job-match-on-demand-sections-design.md)
里写得很明确:

- spec 标题直接写「`extension/background.js`(一次性改成「哑壳」,**之后新功能不再动它**)」
  ([L165-178](superpowers/specs/2026-06-23-job-match-on-demand-sections-design.md#L165-L178))。
- 延伸愿景:未来基于 JD 生成「定制简历」,届时只是**后端多加一个 section + 一个 action,扩展不用改、
  不用重新发版**([L21-22](superpowers/specs/2026-06-23-job-match-on-demand-sections-design.md#L21-L22))。
- 完整的 API 契约见该 spec 的
  [「API 契约」段](superpowers/specs/2026-06-23-job-match-on-demand-sections-design.md#L38-L61)。

## 2. 扩展发送的数据(采集侧)

[extension/content.js](../extension/content.js) 注入页面后,发一条消息给 background:

```js
{ type: "AGENT_BRIDGE_CONTEXT",
  payload: { url, title, selectedText, pageText, imageText } }
```

| 字段 | 来源 | 处理 |
|---|---|---|
| `url` | `location.href` | — |
| `title` | `document.title` | — |
| `selectedText` | 选区文字 | background 会优先用右键事件的选区快照覆盖([background.js:117-121](../extension/background.js#L117-L121)) |
| `pageText` | `document.body.innerText` | 空白压缩后截断到 **20000** 字符([content.js:3](../extension/content.js#L3)) |
| `imageText` | `img[alt]`/`img[title]`/`figcaption`/`[aria-label]` 等 | 去重、最多 **40** 条、截断到 **4000** 字符([content.js:24-32](../extension/content.js#L24-L32)) |

background 收到后,再附加 `agent`(由点击的右键菜单决定)与 `lang`(由弹窗语言偏好解析,
[background.js:131-138](../extension/background.js#L131-L138)),组装成请求体 POST 到网关 `/tasks`。

> 采集侧字段稳定且与「改内容/提升体验」无关;本文档重点是下面的**响应契约**。

## 3. 扩展接收的数据(网关响应契约)——核心

扩展在 `dispatchTask` 里读网关 `/tasks` 返回的 JSON,只认这些顶层字段
([background.js:184-195](../extension/background.js#L184-L195)):

| 字段 | 类型 | 用途 | 缺省 |
|---|---|---|---|
| `result_html` | string | 已净化的 Markdown→HTML,直接注入面板 `body`;第一个 `<p>` 自动升级为 lede([background.js:630-633](../extension/background.js#L630-L633)) | — |
| `sections` | array | 结构化区块;**非空时优先**走分块渲染,`result_html` 被忽略([background.js:588](../extension/background.js#L588)) | `[]` |
| `actions` | array | 结果上可触发的后续动作按钮 | `[]` |
| `result` | string | 原始文本:复制按钮用 + 续跑时作为 `priorResult` 回传([background.js:191](../extension/background.js#L191)) | `""` |
| `detail` | string | 纯文本兜底(无 `result` 时的错误/占位文本) | — |
| `request.url` | string | 来源页地址(面板显示来源、落库指标) | 回退到本地 `source` |
| `duration_ms` | number | 本次耗时 | — |

**渲染优先级**(`renderPanel`):`sections` 非空 → 分块渲染([background.js:588-629](../extension/background.js#L588-L629));
否则有 `result_html` → 整段注入([background.js:630-633](../extension/background.js#L630-L633));
再否则 → `text` 纯文本兜底([background.js:634-636](../extension/background.js#L634-L636))。

### section 对象

分块渲染逻辑见 [background.js:292-328](../extension/background.js#L292-L328):

| 字段 | 类型 | 作用 |
|---|---|---|
| `id` | string | `"conclusion"` 特殊处理为高亮 **lede**;其余渲染成可折叠 `<details>` 区块 |
| `title` | string | 区块标题(`conclusion` 不显示标题) |
| `html` | string | 已净化的 HTML 正文 |
| `collapsible` | bool | `false` = 始终展开;否则正文超过 **160** 字符(`SECTION_COLLAPSE_CHARS`,[background.js:273](../extension/background.js#L273))默认折叠 |
| `copyable` | bool | `true` = 该区块显示「复制」按钮([background.js:314-324](../extension/background.js#L314-L324)) |

### action 对象

动作按钮渲染逻辑见 [background.js:592-611](../extension/background.js#L592-L611):

| 字段 | 类型 | 作用 |
|---|---|---|
| `label` | string | 按钮文字(后端按 `lang` 出中/英) |
| `sections` | array | 点击后续跑时要请求的 section id 列表,扩展**原样回传** `/tasks` |

> 注:网关的 `Action` 模型里还有个 `id` 字段,但**扩展不读 `action.id`**——哑壳只用 `label` + `sections`。
> 因此后端增删/改动 action 的 `id` 不影响扩展。

## 4. 续跑机制(on-demand / `AGENT_BRIDGE_CONTINUE`)

点击 action 按钮后,扩展把上一阶段结果原样带回,触发第二阶段生成
([background.js:598-624](../extension/background.js#L598-L624)):

```js
chrome.runtime.sendMessage({
  type: "AGENT_BRIDGE_CONTINUE",
  sections,                 // action.sections
  priorResult: payload.result,
  lang, url, agent,
});
```

background 的处理器([background.js:221-244](../extension/background.js#L221-L244))用同一个 `/tasks`
重新 POST(请求体带 `sections` + `prior_result`),网关返回**合并后的全量区块**,扩展整体重渲染面板。

关键点:**扩展不保存任何阶段状态**——上下文随消息回传,因此能扛 MV3 service worker 重启。

## 5. 不改扩展就能做的事(纯后端改动)

因为扩展只是「拿到什么渲染什么」,以下全部是后端独占、**不动扩展、不重新发版**:

- ✅ **改文案 / 提示词 / 模型 / 分层路由**——内容质量随便调。
- ✅ **增删 / 重排区块**——后端 `DISPLAY_ORDER` 说了算,扩展只是 `forEach(sections)`。
- ✅ **每区块是否折叠 / 可复制**——`collapsible` / `copyable` 是服务端下发的标志位。
- ✅ **新增 action 按钮**(如「生成定制简历」)——后端往 `actions` 加一项即可。
- ✅ **用更丰富的 Markdown**——标题/列表/表格/`code`/blockquote/链接/`**强调**` 都已在面板 CSS
  里有样式([background.js:421-442](../extension/background.js#L421-L442)),后端多用 Markdown 就更好看。

## 6. 必须改扩展并重新发版的边界

以下触及契约本身,扩展要改代码并重新发 Chrome 商店版:

- ❌ **新增需要扩展读取的 section 属性**(徽章 / 图标 / 新交互类型)。
- ❌ **新增顶层响应字段**(扩展只认第 3 节那张表里的字段)。
- ❌ **action 想做「重打 `/tasks`(带 `sections`+`prior_result`)」以外的事**——例如拆分 URL 走别的端点,
  需要给 action 加一个目标 `path` 字段由壳照打(spec 已预留这个演进方向,
  [L177-178](superpowers/specs/2026-06-23-job-match-on-demand-sections-design.md#L177-L178))。
- ❌ **新渲染原语**:图片、图表、区块内嵌按钮、不同的复制变体等。

## 7. 一句话原则

> **只要新体验能表达成「Markdown 内容 + section 标志位 + action 按钮」,就不用动扩展、不用重新发版。**
