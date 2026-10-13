# 询价报价系统 · 前端镜像（v1.0）
# 多阶段：Node 构建 Vite 产物 → Nginx 托管静态资源 + 反代 /api
FROM node:22-alpine AS build

WORKDIR /app

# 国内构建加速：npm 走 npmmirror。
# 原因：默认 registry.npmjs.org 在国内网络下安装依赖常超时（本项目实测）。
# 海外构建可用 --build-arg NPM_REGISTRY=https://registry.npmjs.org/ 覆盖。
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "${NPM_REGISTRY}"

# 先装依赖，利用层缓存
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build


FROM nginx:1.27-alpine

# 站点配置：SPA history 回退 + /api 反代到后端
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine 自带 wget，可直接用于健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
