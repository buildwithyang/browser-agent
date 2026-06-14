import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev-start 会把服务绑到 dev 域名（默认 dev.buildwithyang.com，可用 DEV_HOST_NAME 覆盖）。
// Vite 默认拦截非白名单 Host，这里把该域名放进 allowedHosts，和 dev-start 保持同源。
const DEV_HOST = process.env.DEV_HOST_NAME || "dev.buildwithyang.com";
// `/api` 反向代理目标（网关）。Vite 服务端到网关是本机直连，浏览器只跟前端自身的源
// 说话，因此完全没有跨域 / 跨站问题，登录 cookie 也落在前端同源上。
const PROXY_TARGET = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:17321";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1", DEV_HOST],
    // 前端所有网关请求(含 /auth/login 跳转)都走 /api -> 由 Vite 转发到网关。
    proxy: {
      "/api": {
        target: PROXY_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
