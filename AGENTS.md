# AGENTS.md — 本项目协作规矩

> 给所有接手的 AI / 人看。**本文件只写规矩，不写项目内容。**
> 接手顺序：`README.md`（现在）→ `doc/TODO.md`（不做什么/想做什么）→ `doc/PRD-询价报价系统.md` §15（做过什么）→ 需要细节时再读 PRD 对应 FR 章节。

## 1. 信息地图：每类信息只写一处

| 信息类型 | 唯一位置 | 不要写进 |
|---|---|---|
| 当前状态、已知问题、下一步 | `README.md` | PRD / TODO |
| 需求规则、状态机、权限、接口契约、验收用例定义（TC） | `doc/PRD-询价报价系统.md` §5/§7/§11 | README |
| 改动的编号与状态（CH-xxx：问题 / 规则 / 状态） | `doc/PRD-询价报价系统.md` **§15** | TODO / README |
| 暂时不做的事、新想法、待真机验证 | `doc/TODO.md` | PRD |
| 部署、运行、账号、环境变量、离线打包、故障排查 | `doc/DEPLOY-DOCKER.md` | README |
| **使用说明（面向使用者的操作手册：每页怎么用、常见问题）** | `doc/USER-GUIDE.md` | README / PRD |
| 逐条验收证据（TC → 状态 + 代码行号） | `doc/ACCEPTANCE-MATRIX.md` | PRD（PRD 只写用例定义） |
| 设计稿 | `doc/design/*.html` | — |
| 演示数据生成 | `scripts/demo_data.py`（用法见 `DEPLOY-DOCKER.md` §2.3） | — |

**单一来源规则**：同一件事只在一处写完整内容；其他地方只允许"一行摘要 + 链接"。
新增内容前先想清楚它属于哪一类，不要第二份"运行说明"或"已知问题清单"。

## 2. 工作流（顺序不能颠倒）

1. **新想法** → 先写进 `doc/TODO.md`（`TODO-xxx`），**不写代码**。
2. **决定要做** → 在 PRD **§15** 建一条 `CH-xxx`：问题、规则、状态填 `待确认`。
3. **等用户确认** → 确认后才能写代码（用户明确说"直接做"可跳过等待，但仍要先建 CH）。
4. **实现完成** → PRD 该 CH 状态改 `已实现`，填落点（文件:行）。
5. **收尾五步** → 见第 3 节。缺一项不算完成。

例外：纯文档/工具脚本的改动也走同样流程，但 CH 类型填 `工程`。

## 3. 收尾五步（每次开发结束必做，缺一不算完成）

- [ ] **PRD 状态**：本次 `CH-xxx` 状态改为 `已实现`（或 `已放弃`），落点填 `文件:行`。
- [ ] **PRD 流水**：在 §15.2 变更流水补一行（日期 / CH / 结论 / 影响文件）。
- [ ] **README**：更新"当前状态"与"下一步"（只写现在，不写历史）。
- [ ] **TODO**：若本项来自 TODO，勾掉并在该条注明结论写在哪（如 `→ CH-003 已实现`）。
- [ ] **回复**：在最终回复里列出本次**回写了哪些文件**。

## 4. 事实与红线（不要臆测，去读代码）

| 约束 | 唯一来源 |
|---|---|
| 时间口径：全站北京时间 naive，唯一时间源 `models.app_now()`；业务代码禁止裸用 `datetime.now()` / `date.today()` | `backend/app/models.py`、`backend/app/utils.py`（有工程门禁校验） |
| 响应式断点：仅 `<768` / `768~1199` / `≥1200`，唯一定义在 SCSS 并注入 JS 常量 | `frontend/src/styles/breakpoints.scss` |
| 接口契约：统一 `{code, message, data}`；金额数量为字符串；错误码表 | `backend/app/schemas.py`、PRD §7.6 |
| 未匹配路由/方法不得透传 HTTP 码，一律映射为 `40400` | `backend/app/main.py` 的 `_HTTP_STATUS_FALLBACK` |
| 数据隔离：供货商按 token 的 `supplier_id`；我方非管理员按 `created_by`——**服务端强制**，前端隐藏按钮不算隔离 | `backend/app/deps.py`、`backend/app/api/report.py::_owner_scope`、PRD §3.3 / FR-RPT-08~10 |
| 提交前自检（三条全绿才算完成） | `cd backend && ./.venv/Scripts/python.exe -m pytest tests -q`；`./backend/.venv/Scripts/python.exe scripts/e2e_acceptance.py`（需后端已启动）；`cd frontend && npm run build` |

## 5. 文档维护禁令

- 不新增第二份"如何运行"或"已知问题"清单——去更新已有那份。
- **不批量补历史变更**：CH 编号只记今后发生的事，历史行为以 PRD FR 正文为准。
- 删除或改名文档时，必须同步修正所有指向它的链接（`grep -rn "旧文件名" .` 确认无残留）。
- 不把大段代码贴进文档；需要时写 `文件:行号`。
