# 采购与项目管理平台

两个相互独立的模块：**采购报价**（我方建单邀请供货商报价 → 比价导出）与**项目管理**（多项目进度看板 + 工期计划表 + 预算决算参考表）。供货商可手机端报价。

> 本文件只写**现在**：当前状态、已知问题、下一步。规则看 PRD，待办看 TODO，部署看部署手册（见文末"文档地图"）。

## 当前状态（2026-10-24）

| 项 | 值 |
|---|---|
| 版本 | **1.0.0**，分支 `main`，与远端同步 |
| 后端 | 23 文件 / ≈8.0k 行，**74 个接口**；`pytest` **67 passed**（2026-10-24 实跑） |
| 前端 | 72 文件 / ≈21.9k 行；`npm run build` 通过（105 个产物，2026-10-24 实跑） |
| 端到端 | `scripts/e2e_acceptance.py` **47 通过 / 0 失败 / 1 跳过**（2026-10-24 实跑） |
| 移动端 | `scripts/mobile-acceptance.sh` 6 个页面元素级验收通过（越界 0、热区 <44px 为 0） |
| 模块 | 采购报价 √ ｜ **项目管理 √（CH-002，与报价无数据关联）** |
| 镜像 | `xunjia-api:1.0`（198MB）、`xunjia-web:1.0`（49.6MB）、`xunjia:1.0` 单镜像（199MB）—— **已含项目管理模块**（2026-10-24 重建，归档在 `release/`） |
| 服务 | 需手动启动，见下节（后端 8000 / 前端 5173） |

## 怎么跑起来

```bat
:: Windows 本机：双击 start.bat（自动检查依赖 → 起后端 8000 + 前端 5173 → 开浏览器）
::               停止用 stop.bat，或直接关闭弹出的两个窗口
start.bat
```

```bash
# 生产/演示（Docker，双镜像或单镜像）
docker compose up -d --build                              # → http://<IP>/
docker compose -f docker-compose.single.yml up -d --build  # → http://<IP>:8000/

# 本地开发（Linux/macOS 或 Git Bash）
bash scripts/dev-all.sh          # 后端 8000 + 前端 5173

# 生成一套可展示的实例数据（11 张单据、含报价与改价历史）
./backend/.venv/Scripts/python.exe scripts/demo_data.py
```

- 完整部署、环境变量、默认账号、离线打包、故障排查 → [doc/DEPLOY-DOCKER.md](doc/DEPLOY-DOCKER.md)
- 三条自检命令（提交前必跑） → [AGENTS.md](AGENTS.md) §4

## 已知问题

| 问题 | 影响 | 去处 |
|---|---|---|
| **移动端 25 条真机专项未执行**（TC-43~TC-67） | **上线阻断项**；模拟器结果不算通过 | [doc/TODO.md](doc/TODO.md) §2 |
| 1366×768 下列表需表内横向滚动（9 列约 1290px） | 不影响功能，属 FR-RWD-01 允许的宽表内滚动 | [doc/TODO.md](doc/TODO.md) TODO-020 |
| 时间按北京时间 naive 存库 | 非 UTC+8 设备上"截止时刻"文字会偏（倒计时不受影响） | [doc/PRD-询价报价系统.md](doc/PRD-询价报价系统.md) §14.5 与 TODO-022 |
| 导入 token 存进程内存 | 多 worker/多实例部署需迁移 Redis/DB（单进程无影响） | [doc/TODO.md](doc/TODO.md) TODO-023 |
| 未指定真机机型清单（Q11） | 真机验收范围未收敛 | [doc/TODO.md](doc/TODO.md) TODO-024 |
| 演示数据需手动执行脚本 | 新环境默认只有 3 张示例单据、无报价数据 | [doc/DEPLOY-DOCKER.md](doc/DEPLOY-DOCKER.md) §2.3 |
| 项目管理手机端表格为**表格内部横滚**（未做卡片化） | 页面级不横滚，但手机上编辑 10 列工期表体验一般 | [doc/TODO.md](doc/TODO.md) TODO-046 |
| 报价与项目两模块**暂不关联** | 询价单的 `project` 仍是自由文本，不指向项目主数据 | [doc/TODO.md](doc/TODO.md) TODO-047 |
| 按需求**不做**消息通知、审批流、定标下单、小程序等 | 属范围排除，不是缺陷 | [doc/TODO.md](doc/TODO.md) §1 |

## 下一步

1. **跑真机验收**：按 [doc/TODO.md](doc/TODO.md) §2 的分组执行 TC-43~TC-67，结果回填 [doc/ACCEPTANCE-MATRIX.md](doc/ACCEPTANCE-MATRIX.md)。
2. **验收项目管理模块**：`/pm` 看板 + 工期计划表编辑 + 三张参考表维护（详见 PRD §5.6）。
3. **部署验收**：镜像已含项目管理模块，可在容器里跑一遍 `/pm` 看板与工期计划表。
4. **需求方确认待定项**：`TODO-020`（1366 是否收窄列）、`TODO-022`（多时区）、`TODO-024`（机型清单）、`TODO-047`（两模块是否打通）。
5. **生产上线前**：替换 `XUNJIA_SECRET_KEY`、关闭 `SEED_DEMO`、按数据量评估是否切 PostgreSQL。
6. 新需求/新想法先记 [doc/TODO.md](doc/TODO.md)；确定要做再按 [AGENTS.md](AGENTS.md) §2 建 `CH-xxx` 并等确认。

## 文档地图

| 想知道 | 看 |
|---|---|
| 现在什么状态、有什么毛病、接下来做什么 | 本文件 |
| 需求规则、状态机、权限、接口契约、验收用例定义 | [doc/PRD-询价报价系统.md](doc/PRD-询价报价系统.md) |
| 改动编号与状态（`CH-xxx`）、变更流水 | PRD **§15** |
| 暂时不做的事、新想法、待真机验证 | [doc/TODO.md](doc/TODO.md) |
| 部署、运行、账号、环境变量、离线打包、排障 | [doc/DEPLOY-DOCKER.md](doc/DEPLOY-DOCKER.md) |
| Windows 一键启动/停止脚本 | [doc/DEPLOY-DOCKER.md](doc/DEPLOY-DOCKER.md) §2.0（`start.bat` / `stop.bat`） |
| 逐条验收证据（TC → 状态 + 代码行号） | [doc/ACCEPTANCE-MATRIX.md](doc/ACCEPTANCE-MATRIX.md) |
| 页面设计稿（4 份自包含 HTML） | [doc/design/01-design-system.html](doc/design/01-design-system.html) |
| 协作规矩、信息该写哪里、收尾要求 | [AGENTS.md](AGENTS.md)（`CLAUDE.md` 为一行引用） |

## 技术栈与目录

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x + Pydantic v2 + PyJWT/bcrypt |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router（三档响应式断点） |
| 数据 | SQLite（WAL；可选 PostgreSQL 16 profile）；openpyxl/xlrd 处理 Excel |
| 部署 | Linux + Docker Compose（nginx 托管前端或单镜像 FastAPI 直出） |

```
xunjia/
├─ AGENTS.md / CLAUDE.md     协作规矩（先读）
├─ README.md / Dockerfile.single
├─ docker-compose.yml        双镜像编排；docker-compose.single.yml 单镜像
├─ backend/app/              23 个模块：api/（7 组路由，含 pm.py）、models、schemas、
│                            deps、security、importer、exporter、seed、pm_seed、scheduler
├─ backend/tests/            10 个测试文件（67 用例：隔离/时间口径/导入/项目管理等）
├─ frontend/src/             views（purchase / pm / supplier / system）、layouts、
│                            components（DataTable 等）、api、stores、router、styles
├─ scripts/                  e2e_acceptance.py、mobile-acceptance.sh、demo_data.py、dev-*.sh
└─ doc/                      PRD、TODO、ACCEPTANCE-MATRIX、DEPLOY-DOCKER、design/、示例.xls
```
