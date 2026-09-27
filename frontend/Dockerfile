# Build context is frontend/ (see deploy/docker-compose.yml's `build: ../frontend`).
FROM node:22-alpine AS builder
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1, not localhost: this image's musl/BusyBox wget resolves
# "localhost" to ::1 (IPv6) first, but nginx here only binds 0.0.0.0:80
# (IPv4) -- found live, this container reported unhealthy indefinitely
# despite actually serving every real request correctly (confirmed via
# `docker exec ... wget http://127.0.0.1/` succeeding while `wget
# http://localhost/` failed with "Connection refused" in the same shell).
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1
