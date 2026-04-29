# Router API 镜像（离线模式）
# 复用 Dockerfile.api 模式：node_modules 在宿主机预装
FROM node:18-alpine

WORKDIR /app

COPY router/package.json ./
# 离线：直接 COPY 预装好的 node_modules
COPY router/node_modules ./node_modules
COPY router/server.js ./
COPY router/lib ./lib
COPY router/config ./config

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://localhost:3000/health || exit 1

CMD ["node", "server.js"]
