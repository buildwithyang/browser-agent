# Agent Bridge · 简历管理前端

独立的 React (Vite) 单页应用：用户登录（Casdoor）、上传简历（OSS 预签名直传）、管理多份简历并选择「生效简历」。生效简历会被浏览器扩展的「与简历匹配」功能使用。

## 开发

```bash
cd frontend
cp .env.example .env        # 按需修改 VITE_GATEWAY_URL
npm install
npm run dev                 # http://127.0.0.1:5173
```

需要后端网关同时运行（默认 `http://127.0.0.1:17321`，见 `gateway/`）。

- `VITE_EXTENSION_ID`：已安装扩展的 ID，用于把登录 token 推送给扩展。加载 unpacked 扩展后从 `chrome://extensions` 复制。
  > ⚠️ 验证扩展连接时前端必须跑在 `dev.buildwithyang.com:5173`（`npm run dev` 已配该域名），**不能用 `127.0.0.1`**——`externally_connectable` 不匹配 IP。

前端逻辑测试：`npm test`（vitest）。

## 界面语言

前端支持中文、English 和 Français。首次访问时优先使用浏览器支持的语言，无法匹配时默认英文；用户也可以通过顶栏的语言下拉框手动切换，选择会保存在浏览器本地。

本次多语言范围仅包含公开落地页、登录后的简历管理页和扩展连接卡片。Chrome 扩展界面、AI 生成结果及隐私政策正文使用各自独立的语言机制，不随前端选择切换。

## 与后端的关系（同源 `/api` 代理）

开发时前端**不直接跨域**访问网关，而是统一走同源 `/api`，由 Vite 反向代理转发到网关
（`vite.config.js` 的 `server.proxy`，目标默认 `http://127.0.0.1:17321`，可用 `VITE_PROXY_TARGET` 覆盖）。
这样浏览器只跟前端自身的源说话，登录 cookie 落在前端同源上，**没有跨域 / 跨站问题**。

- 登录是整页跳转：`/api/auth/login` → 网关 302 到 Casdoor → 回调 → 跳回前端。因此 Casdoor 的
  **回调地址要填「前端 + `/api/auth/callback`」**（如 `http://dev.buildwithyang.com:5173/api/auth/callback`），
  而不是网关直连地址——cookie 才能被回调读到。网关 `.env` 的 `CASDOOR_REDIRECT_URI` / `AUTH_FRONTEND_REDIRECT_URL` 同理填前端地址。
- 普通接口（`/api/auth/me`、`/api/resumes` 等）都带 `credentials: "include"`，经代理同源发出。
- 上传是「预签名直传」：前端先向网关要预签名 PUT 地址，再把文件**直传到 OSS**（这一步是 OSS 绝对地址，不走代理），最后通知网关回源解析入库。
- 因此 **OSS bucket 需要配置 CORS**，允许本前端 Origin 的 `PUT` 与 `ETag` 响应头，否则浏览器直传会被拦。

## 构建部署

```bash
npm run build               # 产物在 dist/
```

`dist/` 是纯静态资源，可托管在任意静态服务 / CDN（**没有 Vite 代理**）。部署时通过 `VITE_GATEWAY_URL`
把接口基址指向云端网关 HTTPS 绝对地址，并把该前端 Origin 配进网关的 `AUTH_FRONTEND_REDIRECT_URL` 与 CORS 白名单；
Casdoor 回调按生产同站域名配置。

## 结构

```text
frontend/
|- index.html
|- vite.config.js
|- src/
   |- main.jsx      # 挂载
   |- App.jsx       # 登录态 + 上传 + 简历列表
   |- api.js        # 网关接口封装 + 预签名上传流程
   |- styles.css    # 深色「仪表盘」主题，与扩展面板同源
```
