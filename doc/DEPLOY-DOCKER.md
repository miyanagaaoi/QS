# 容器化部署说明（v1.0）

本文档说明如何用 Docker Compose 部署本系统。适用于 Linux 服务器（内网部署）。

## 1. 前置条件

- Docker Engine 20.10+ 与 Docker Compose v2（`docker compose version` 可验证）
- 端口：`80`（前端，可改）、`8000`（后端，仅容器内网，无需对外）
- 磁盘：镜像约 250MB + 数据目录

## 2. 快速启动

```bash
# 1) 准备环境变量（至少改密钥与管理员密码）
cp .env.example .env 2>/dev/null || true
export XUNJIA_SECRET_KEY="$(openssl rand -hex 32)"
export INITIAL_ADMIN_PASSWORD='YourStrongPassword123'

# 2) 构建并启动
docker compose up -d --build

# 3) 查看状态（两个容器都应为 healthy）
docker compose ps

# 4) 访问
#    前端  http://<服务器IP>/
#    接口文档 http://<服务器IP>/docs
```

首次启动会自动建库（SQLite）并创建管理员账号 `admin`，密码取 `INITIAL_ADMIN_PASSWORD`。
**启动日志会打印该账号**，可用 `docker compose logs api | grep 管理员` 查看。

## 3. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_PORT` | `80` | 前端对外端口（如与现有服务冲突改成 `8080`） |
| `XUNJIA_SECRET_KEY` | 无（**必须设置**） | JWT 签名密钥；不设置则每次重启导致已登录会话失效 |
| `INITIAL_ADMIN_PASSWORD` | 随机生成并打印日志 | 首次建库时的管理员密码 |
| `SEED_DEMO` | `0` | 设为 `1` 会额外创建演示数据（仅用于演示/验收） |
| `XUNJIA_DATABASE_URL` | `sqlite:////app/data/xunjia.db` | 数据库连接串 |
| `TZ` | `Asia/Shanghai` | 容器时区，与后端北京时间口径一致 |
| `APT_MIRROR` / `PIP_INDEX` / `NPM_REGISTRY` | 国内镜像源 | 构建加速；海外构建可覆盖为官方源 |

## 4. 数据持久化

| 挂载 | 内容 | 说明 |
|---|---|---|
| `./data` → `/app/data` | SQLite 数据库 + 上传附件 | **必须备份此目录** |

备份示例：

```bash
docker compose stop api
tar czf xunjia-backup-$(date +%Y%m%d).tar.gz data/
docker compose start api
```

## 5. 无网络服务器部署（离线）

在可联网机器上导出镜像：

```bash
docker pull python:3.12-slim && docker pull nginx:1.27-alpine && docker pull node:22-alpine
docker compose build
docker save xunjia-api:1.0 -o xunjia-api-1.0.tar
docker save xunjia-web:1.0 -o xunjia-web-1.0.tar
```

把两个 tar 与项目目录拷贝到目标服务器：

```bash
docker load -i xunjia-api-1.0.tar
docker load -i xunjia-web-1.0.tar
docker compose up -d          # 镜像已存在，无需 --build
```

> 若目标服务器完全离线且没有 `python`/`nginx` 基础镜像，用上面 save 的 tar 即可，
> 因为 xunjia-api / xunjia-web 已包含全部依赖，`docker compose up -d` 不会再拉基础镜像。

## 6. 常用运维命令

```bash
docker compose ps                 # 状态与健康
docker compose logs -f api        # 后端日志
docker compose logs -f web        # nginx 日志
docker compose restart api        # 重启后端
docker compose down               # 停止（保留数据）
docker compose down -v            # 停止并删除数据卷（⚠️ 会清库）
```

## 7. 切换到 PostgreSQL（可选）

系统默认用 SQLite（适合 3~4 人 + ≤50 家供货商的规模）。如需 PostgreSQL：

```bash
docker compose --profile postgres up -d
```

并把 `XUNJIA_DATABASE_URL` 改为
`postgresql+psycopg://xunjia:<密码>@db:5432/xunjia`。

## 8. 故障排查

| 现象 | 原因与处理 |
|---|---|
| `dependency failed to start: container xunjia-api is unhealthy` | 多因 `XUNJIA_SECRET_KEY` 未设置或 `./data` 权限不足；看 `docker compose logs api` |
| 页面能开但接口 502 | 后端未就绪或崩溃。确认 `docker compose ps` 里 api 是 healthy；nginx 已配置运行时 DNS 解析，后端重启后可自动恢复 |
| 登录后立刻要求重新登录 | `XUNJIA_SECRET_KEY` 未固定（每次重启换了密钥） |
| 构建卡在 `apt-get update` / `npm install` | 网络问题。Dockerfile 默认走国内源，海外环境用 `--build-arg` 覆盖为官方源 |
| 时间显示差 8 小时 | 确认容器 `TZ=Asia/Shanghai`（`docker exec xunjia-api date` 应显示 CST） |

## 9. 健康检查说明

两处健康检查**都**必须正确（compose 会覆盖镜像自带的定义）：

- `backend/Dockerfile` 的 `HEALTHCHECK`
- `docker-compose.yml` 中 api 服务的 `healthcheck`

两者均使用容器自带的 `python` 探测 `/api/health`，**不依赖 curl**
（`python:3.12-slim` 基础镜像不含 curl）。
