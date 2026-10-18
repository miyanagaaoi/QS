# 询价报价系统

小型询价报价系统：我方人员创建/导入询价单并邀请供货商，供货商登录后在线报价（手机端可用），我方在统计报表中比价与导出。

- 需求文档：[doc/PRD-询价报价系统.md](doc/PRD-询价报价系统.md)（v1.2）
- 页面设计稿：[doc/design/01-design-system.html](doc/design/01-design-system.html)（入口页，可直接用浏览器打开）

## 功能范围

| 模块 | 说明 |
|---|---|
| 采购管理 → 报价单 | 新建/Excel 导入询价单、明细录入、发布分派、撤回、截止、报价进度催办、导出 |
| 采购管理 → 报价单统计报表 | 视图 A 交叉比价（最低价高亮）、视图 B 汇总统计、导出 .xlsx |
| 系统管理 → 账号管理 | 我方账号、供货商账号、批量导入（含错误报告）、启停用、重置密码、操作日志 |
| 供货商侧 | 待报价列表、**手机端报价填报**（分段导航、拍照上传、弱网容错、截止只读） |

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x + Pydantic v2 |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router |
| 数据库 | SQLite（原型）→ PostgreSQL 16（可选 profile） |
| Excel | 后端 openpyxl 导出/导入，xlrd 兼容 .xls |
| 部署 | Linux + Docker Compose |

> 运行环境说明：PRD 原选型为 Python 3.11+，实测落地 **3.12**（依赖全部通过 PyPI 安装并验证）。代码未使用 3.12+ 独有语法，可向下兼容 3.11。

## 快速开始

### 方式一：Docker Compose（推荐，生产/演示）

```bash
# 1) 准备环境变量（至少改密钥）
export XUNJIA_SECRET_KEY=$(openssl rand -hex 32)
export INITIAL_ADMIN_PASSWORD=Admin@2026      # 首次启动创建 admin 用；不设则随机生成并打印到日志
export SEED_DEMO=1                            # 需要演示数据时设为 1（生产保持 0）

# 2) 启动
docker compose up -d --build

# 3) 访问
#    前端  http://<服务器IP>/
#    API文档 http://<服务器IP>/docs
```

镜像标签：`xunjia-api:1.0`、`xunjia-web:1.0`（双镜像）。
如需**单镜像**（一个容器一个端口，FastAPI 直接托管前端）：
```bash
docker compose -f docker-compose.single.yml up -d --build   # → http://<IP>:8000/
```
**离线部署、数据备份、环境变量表、故障排查**见 [doc/DEPLOY-DOCKER.md](doc/DEPLOY-DOCKER.md)。

查看初始管理员密码：`docker compose logs api | grep 管理员`。

数据（SQLite 文件与上传附件）持久化在 `./data`，备份即复制该目录。

### 方式二：本地开发

```bash
# 后端
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux
cp .env.example .env            # 修改 XUNJIA_SECRET_KEY
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                     # http://127.0.0.1:5173
```

或一键启动前后端：`bash scripts/dev-all.sh`

### 默认账号

| 角色 | 账号 | 密码 |
|---|---|---|
| 管理员 | admin | `XUNJIA_ADMIN_PASSWORD` 的值 |
| 采购员 | wangcaigou | `XUNJIA_BUYER_PASSWORD`（默认 buyer123） |
| 供货商 | hengxin_wenju 等 5 个 | `XUNJIA_DEMO_PASSWORD`（默认 supplier123） |

采购员与供货商账号仅在 `XUNJIA_SEED_DEMO=1` 时创建。**所有初始账号首次登录强制修改密码。**

## 环境变量

见 [backend/.env.example](backend/.env.example)。关键项：

| 变量 | 说明 | 默认 |
|---|---|---|
| `XUNJIA_SECRET_KEY` | JWT 签名密钥，**生产必改** | dev 占位值 |
| `XUNJIA_DATABASE_URL` | 数据库连接串 | `sqlite:///./data/xunjia.db` |
| `XUNJIA_ADMIN_PASSWORD` | 初始管理员密码，空则随机生成并打印日志 | 空 |
| `XUNJIA_SEED_DEMO` | 是否写入演示数据 | 0 |
| `XUNJIA_UPLOAD_DIR` | 附件目录 | `./data/uploads` |
| `XUNJIA_ACCESS_TOKEN_EXPIRE_MINUTES` | token 有效期（内网默认 8 小时） | 480 |
| `XUNJIA_BCRYPT_ROUNDS` | 密码哈希轮数（测试可调低） | 12 |

## 项目结构

```
xunjia/
├─ doc/                       需求文档与页面设计稿
│  ├─ PRD-询价报价系统.md
│  ├─ 示例.xls                甲方提供的示例报价单（OLE2 格式）
│  └─ design/                 4 份 HTML 设计稿（可直接打开）
├─ backend/
│  ├─ app/
│  │  ├─ main.py              应用入口与路由注册
│  │  ├─ config.py            配置（pydantic-settings）
│  │  ├─ database.py          引擎与会话（SQLite WAL）
│  │  ├─ models.py            SQLAlchemy 模型
│  │  ├─ schemas.py           接口契约（Pydantic）
│  │  ├─ security.py          bcrypt + JWT（含密码指纹）
│  │  ├─ deps.py              鉴权与角色守卫
│  │  ├─ utils.py             单号、金额、状态计算
│  │  ├─ seed.py              初始数据与演示数据
│  │  ├─ importer.py / exporter.py  Excel 导入导出
│  │  └─ api/                 auth / meta / admin / rfq / supplier / report
│  ├─ tests/                  pytest 用例
│  ├─ requirements.txt
│  └─ Dockerfile
├─ frontend/
│  ├─ src/
│  │  ├─ api/                 axios 封装与各模块接口
│  │  ├─ router/              路由与角色守卫
│  │  ├─ stores/              Pinia
│  │  ├─ layouts/             AdminLayout / SupplierLayout
│  │  ├─ components/          DataTable / StickyBar / StatusBadge 等
│  │  ├─ composables/         useBreakpoint / useFormat
│  │  └─ views/               login、purchase、supplier、system
│  ├─ nginx.conf
│  └─ Dockerfile
├─ scripts/                   开发启动脚本
└─ docker-compose.yml
```

## 响应式与手机端

三档断点：手机 `<768px`、平板 `768~1199px`、桌面 `≥1200px`。

- **供货商侧手机优先**：待报价列表卡片化、报价填报页每行物料一张卡片（默认只展开"含税单价"）、底部吸底操作栏、>10 行分段导航、拍照上传、弱网不清空。
- **我方侧桌面优先**：宽表在手机端转卡片或内部横向滚动；Excel 导入与批量导入等重操作在手机端隐藏并提示到电脑操作。

详细规范见 PRD 第 10 章。

## 测试与验收

```bash
# 1) 后端单元/接口测试（41 条，覆盖鉴权、越权隔离、导入校验、时间口径等）
cd backend
./.venv/Scripts/python.exe -m pytest tests -q

# 2) 端到端业务闭环验收（42 项，含时间口径门禁；需后端已启动）
cd ..
./backend/.venv/Scripts/python.exe scripts/e2e_acceptance.py
# 可选参数：--base http://127.0.0.1:8000 --admin-password Admin@2026

# 3) 前端纯逻辑自检（供货商报价模型 29 项，无需浏览器）
cd frontend
node src/views/supplier/__verify__/verify_quote_contract.mjs

# 4) 前端构建
npm run build
```

端到端脚本覆盖：认证与强制改密、询价单发布与分派、发布前校验、已发布禁改明细、
供货商保存/改价（版本递增）、不含税单价自动计算、越权 40300 与留痕、比价最低价与
价差率、三类 xlsx 导出、操作日志只读、最后管理员保护、以及**时间口径工程门禁**。

验收证据与用例对照见 [doc/ACCEPTANCE-MATRIX.md](doc/ACCEPTANCE-MATRIX.md)；
`backend/data/test_artifacts/` 保留了批量导入模板、含错样例与导出产物等可复查证据。

## 已知限制

| 限制 | 说明 | 影响/规避 |
|---|---|---|
| **时间口径为北京时间** | 全应用统一使用北京时间 naive（`models.app_now()`）。这是内网单时区部署的刻意选择：管理员填 18:00 即 18:00 截止。 | 供货商若用**非 UTC+8 时区**的手机，"截止时刻"文字会偏（**倒计时不受影响**，走 `remaining_seconds`）。如将来需多时区，应改为存储 tz-aware UTC + 接口标注时区（`utils.to_app_tz` 已集中在单点，改造面小）。 |
| Excel 导入 token 存于进程内存 | 30 分钟有效、一次性 | 多 worker 部署需迁移到 Redis/DB（`api/admin.py` 顶部已注明） |
| SQLite 并发写 | 已开 WAL + busy_timeout | 供货商规模增长后建议切 PostgreSQL（compose 已提供 `postgres` profile） |
| 自动截止为"惰性 + 定时兜底" | 接口读写时惰性判定，另有后台任务每 60s 扫描一次（`services/scheduler.py`） | 无需用户操作即可按时截止；多 worker 部署时该任务会在每个 worker 各跑一次（幂等，无副作用） |
| 无消息通知 | 本期按需求不做邮件/短信 | 供货商登录后自行看到待报价；催办依赖「报价进度」页的未报价名单 |
| 未做 ESLint / TypeScript | 前端为 JS | 体量小、单人开发；如需接入可在 `package.json` 增加 |
| 批量导入仅支持 .xlsx | 询价明细导入兼容 .xls（xlrd） | 账号批量导入模板统一要求 .xlsx |
| 附件仅供货商可上传 | 我方未提供"行图纸上传"入口 | 属本期范围外（PRD 未列），如需请派单 |

## 安全说明

- 密码使用 bcrypt（12 轮）加盐哈希存储
- JWT 含密码指纹，**改密或重置密码后旧 token 立即失效**
- 供货商数据隔离在服务端强制：供货商身份只来自 token 中的 `supplier_id`，接口不接受前端传入
- 供货商访问报表接口一律 403 并写入越权告警日志
- **我方账号数据隔离**：除管理员外，采购员只能看到自己创建的询价单——列表、详情、进度、
  比价/汇总报表以及全部导出均按创建人在服务端过滤；访问他人单据返回 40300 并写审计日志
  （前端仅做提示，不作为隔离手段）
- 操作日志只追加，无任何删除入口
- 生产部署务必：修改 `XUNJIA_SECRET_KEY`、关闭 `SEED_DEMO`、将 `.env` 排除在版本控制外（已在 .gitignore）
