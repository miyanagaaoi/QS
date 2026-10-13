# 容器化部署说明（v1.0）

本文档说明如何用 Docker 部署本系统。适用于 Linux 服务器（内网部署）。

系统提供**两种镜像方案**，二选一即可：

| | 双镜像（默认） | 单镜像 |
|---|---|---|
| 文件 | `docker-compose.yml` + `backend/Dockerfile` + `frontend/Dockerfile` | `docker-compose.single.yml` + `Dockerfile.single` |
| 容器数 | 2（`xunjia-api` + `xunjia-web`） | 1（`xunjia-app`） |
| 镜像 | `xunjia-api:1.0`(198MB) + `xunjia-web:1.0`(49.6MB) = 248MB | `xunjia:1.0`(199MB) |
| 对外端口 | `80`（nginx 托管前端并反代 `/api`） | `8000`（FastAPI 同时托管前端与 `/api`） |
| 归档 tar | 196M + 49M = 245M | 197M |
| 优势 | 前后端可独立重建/发布；nginx 承担静态缓存与 gzip | 一个容器一个端口，交付/迁移最简单 |
| 建议 | 正式部署 | 资源紧张、或希望"一个 tar 一个容器"跑起来 |

两者功能完全一致（单镜像的前端由 FastAPI 托管，复用后端既有的 SPA history 回退）。

## 1. 前置条件

- Docker Engine 20.10+ 与 Docker Compose v2（`docker compose version` 可验证）
- 双镜像：端口 `80`（前端，可改）+ `8000`（后端，仅容器内网）
  单镜像：端口 `8000`（可改，唯一对外端口）
- 磁盘：镜像约 200~250MB + 数据目录

## 2. 快速启动

### 2.1 双镜像（推荐用于正式部署）

```bash
# 1) 准备环境变量（至少改密钥与管理员密码）
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

### 2.2 单镜像（一个容器一个端口）

```bash
export XUNJIA_SECRET_KEY="$(openssl rand -hex 32)"
export INITIAL_ADMIN_PASSWORD='YourStrongPassword123'
export APP_PORT=8000            # 需要改端口时设置

docker compose -f docker-compose.single.yml up -d --build

# 访问：http://<服务器IP>:8000/   接口文档 /docs
```

不用 compose、直接跑单个容器也可以：

```bash
docker build -f Dockerfile.single -t xunjia:1.0 .
docker run -d --name xunjia-app -p 8000:8000 \
  -e XUNJIA_SECRET_KEY="$(openssl rand -hex 32)" \
  -e XUNJIA_ADMIN_PASSWORD='YourStrongPassword123' \
  -v "$(pwd)/data:/app/backend/data" \
  xunjia:1.0
```

> 单镜像的构建上下文是**项目根目录**，因此根目录的 `.dockerignore` 已排除
> `frontend/node_modules`、`backend/.venv`、`data`、`release`、文档等
> （上下文从 457MB 压到约 3.6MB）。改动这些排除项会显著影响构建速度。

首次启动会自动建库（SQLite）并创建管理员账号 `admin`，密码取 `INITIAL_ADMIN_PASSWORD`。
**启动日志会打印该账号**，可用 `docker compose logs api | grep 管理员` 查看。

## 2.3 生成演示数据（可选）

交付演示或功能验收前，可一键生成一套覆盖各状态的实例数据：

```bash
# 需后端已启动；脚本全程走 API，可重复运行（每次先清理旧的演示数据）
python scripts/demo_data.py                                  # 默认 http://127.0.0.1:8000
python scripts/demo_data.py --base http://127.0.0.1:18000    # 单镜像容器
```

生成内容：11 张询价单（6 张已截止 / 3 张进行中，其中 2 张只报了一半用于催办场景 /
2 张草稿，含 1 张无明细的不完整草稿）、164 条报价行（覆盖 4 档税率、MOQ、交期、到货日期、
备注）、188 条改价历史、41 条分派，响应率约 73%，最低价分散在不同供货商以便体现比价价值。

> 生成后可直接用 `admin / Admin@2026` 登录查看；供货商账号密码会统一为 `supplier123`
> （便于切换账号演示手机端填报）。

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

**单镜像的离线部署更简单**（只需一个 tar）：

```bash
# 联网机器上
docker build -f Dockerfile.single -t xunjia:1.0 .
docker save xunjia:1.0 -o xunjia-single-1.0.tar

# 目标服务器上
docker load -i xunjia-single-1.0.tar
docker run -d --name xunjia-app -p 8000:8000 \
  -e XUNJIA_SECRET_KEY="$(openssl rand -hex 32)" \
  -e XUNJIA_ADMIN_PASSWORD='YourStrongPassword123' \
  -v /opt/xunjia/data:/app/backend/data \
  xunjia:1.0
```

## 6. 常用运维命令

```bash
# 双镜像
docker compose ps                 # 状态与健康
docker compose logs -f api        # 后端日志
docker compose logs -f web        # nginx 日志
docker compose restart api        # 重启后端
docker compose down               # 停止（保留数据）
docker compose down -v            # 停止并删除数据卷（⚠️ 会清库）

# 单镜像
docker compose -f docker-compose.single.yml ps
docker compose -f docker-compose.single.yml logs -f app
docker logs -f xunjia-app         # 直接跑容器时
docker restart xunjia-app
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
