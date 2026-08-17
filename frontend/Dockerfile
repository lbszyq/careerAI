# CareerAI 前端镜像（多阶段：node 构建 → nginx 静态托管）
# 构建阶段：node 20 LTS（Vite 5 / React 18 要求 Node >= 18）
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# 运行阶段：nginx 1.27 提供静态资源 + /api 反向代理 backend
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
