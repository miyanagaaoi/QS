# 询价报价系统 · 前端镜像（多阶段：Vite 构建 → Nginx 托管 + 反代 /api）
FROM node:22-alpine AS build

WORKDIR /app

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
