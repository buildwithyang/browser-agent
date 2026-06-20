# Agent Bridge 前端镜像：多阶段构建（Node 构建静态产物 → nginx 托管）。
# 构建上下文 = 仓库根。
#   docker compose -f deploy/docker-compose.yml build web

# ---- 构建阶段 ----
FROM node:20-alpine AS build
WORKDIR /app

# 先装依赖（命中缓存层）。有 package-lock.json，用 npm ci 保证可复现。
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# 再拷源码并构建。
# 不传 VITE_GATEWAY_URL → api.js 回退到同源 "/api"，由 nginx 反代到网关，
# 复刻开发期 Vite /api 代理，避免跨站 cookie / CORS。
COPY frontend/ ./
RUN npm run build

# ---- 运行阶段 ----
FROM nginx:alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
