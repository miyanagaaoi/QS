# PRD 验收矩阵（TC-01 ~ TC-67）

> 交付物：`doc/ACCEPTANCE-MATRIX.md`
> 依据：`doc/PRD-询价报价系统.md` 第 11 章「验收用例」（PRD L965–L1071），逐条抄录，未凭记忆。
> 代码快照：2026-10-13 20:39（后端 `backend/app/`、前端 `frontend/src/`）。
> 说明：本矩阵生成期间前端多个页面正在并行交付（20:33 时仍有 8 个 `fe-base-placeholder` 占位页）；至 20:39 前端页面已全部交付，但**未经人工走查**，因此矩阵中所有前端相关用例仍按「已实现待验证」处理，不臆断通过。
> 证据位置中的**行号均为本次实际 grep 得到的当前代码行号**；代码继续变更后需重新核对。

---

## 1. 交付结论（覆盖统计）

| 实现状态 | 条数 | 占比 | 说明 |
|---|---|---|---|
| 已实现并通过 | 27 | 40.3% | 用例中可机检的核心行为（错误码 / 数据 / 文件 / 日志）已被自动化测试（pytest、e2e 脚本）或留存产物覆盖 |
| 已实现待验证 | 40 | 59.7% | 核心验收点落在页面交互 / 视觉 / 真机，或需人工比对；其中 25 条为 PRD 强制真机专项 |
| 未实现（本期排除） | 0 | 0% | 67 条用例均在范围内；PRD 1.3 排除项没有对应验收用例（清单见第 4.1 节） |
| 不适用 | 0 | 0% | — |
| **合计** | **67** | 100% | — |

**后端**：6 个路由模块全部实现并实测通过；`pytest tests/` = **29 passed**（生成时点，含 `tests/test_admin.py` 11 条）；端到端脚本 `scripts/e2e_acceptance.py`（7 个分节 [0]–[6]）由 lead 执行全绿。

**前端**：生成期间 8 个页面曾为 `fe-base-placeholder` 占位页（`RfqEdit`/`RfqProgress`/`RfqReport`/`QuoteFill`/`QuoteList`/`AccountList`/`AuditLog`/`DictList`）；至快照时点**已全部交付**：`RfqEdit` 1780 行、`RfqReport` 1281 行、`RfqProgress` 754 行、`RfqList` 717 行、`QuoteFill` 1119 行、`QuoteList` 704 行、`AccountList` 1467 行、`SupplierImport` 655 行、`SupplierArchivePanel` 512 行、`AuditLog`/`DictList` 亦已实现；`frontend/dist/` 已构建。但**均未经人工走查**，因此凡预期结果包含页面行为的用例一律标记「已实现待验证」。

### 判定口径（本矩阵统一执行）

1. **已实现并通过** = 用例中可机检的核心行为已被自动化或留存证据覆盖。证据列标注 `⚠UI` 的部分（页面渲染、提示文案、按钮可达性）仍建议人工确认一次，不因本条判定而视为免检。
2. **已实现待验证** = 核心验收点依赖页面交互 / 视觉 / 真机，或缺少自动化与留存证据。
3. 证据列**不允许出现「已实现」这类无证据表述**；每条至少给出一个可复查的 `文件:行号`、测试函数名或产物路径。
4. 部分用例的操作场景比自动化用例更细（如「2/10 行」而自动化覆盖「1/3 行」），证据列中会显式说明，必要时人工复跑。

---

## 2. 逐条验收矩阵

### 2.1 账号与鉴权（TC-01 ~ TC-07）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-01 | 错误密码登录：统一提示「用户名或密码错误」，不暴露账号是否存在，并记失败日志 | 已实现并通过 | 代码审查+curl手工 | `backend/app/api/auth.py:36-49`（`ok = bool(user) and verify_password(...)` → 单一 message，40100）；失败留痕 `backend/app/api/auth.py:38-48`；留存实例 `backend/data/test_artifacts/verify_audit_logs.txt:2`（`action=auth.login_failed`，operator=system） |
| TC-02 | 供货商首次登录强制跳改密页，其他接口返回 40101 | 已实现并通过 | pytest+e2e脚本 | `backend/app/deps.py:76-83`（must_change_password → 40101，白名单见 `deps.py:32-40`）；`backend/tests/test_admin.py::test_reset_password_forces_change_and_blocks_business_api:402`；`scripts/e2e_acceptance.py` [1]:188-213；⚠UI 改密页 `frontend/src/views/ChangePassword.vue` 需人工走查跳转 |
| TC-03 | 供货商改密后重新登录可正常进入待报价列表 | 已实现待验证 | 前端功能 | 服务端改密：`backend/app/api/auth.py:104-122`；前端列表：`frontend/src/views/supplier/QuoteList.vue:5,107-112`（卡片+我的报价状态）；需人工在 PC/手机走查「改密 → 列表」 |
| TC-04 | 账号被停用后登录被拒，提示账号已停用 | 已实现并通过 | pytest+代码审查 | `backend/app/api/auth.py:52-63`（40100「账号已停用，请联系管理员」）；已登录会话立即失效 `backend/app/deps.py:70-72`；`backend/tests/test_admin.py::test_supplier_account_binds_archive_one_to_one:742`（断言停用账号登录 401/40100） |
| TC-05 | 仅剩一个启用管理员时，停用该管理员被拒绝 | 已实现并通过 | pytest+curl手工 | `backend/app/api/admin.py:179-204`（`_guard_last_admin` → 409/40900，拒绝动作写 audit_log）；`backend/tests/test_admin.py::test_last_enabled_admin_cannot_be_disabled_or_demoted:162`；真实 curl 输出 `backend/data/test_artifacts/curl_isolated_last_admin.txt:9,12,26`；⚠UI 提示文案：`frontend/src/views/system/AccountList.vue:263-290`（`toggleUser`→`api.toggleUserStatus`，需人工确认 40900 提示呈现） |
| TC-06 | 管理员重置供货商密码后原会话失效，下次登录强制改密 | 已实现并通过 | pytest | JWT 密码指纹 `backend/app/security.py:32-40`；比对不符 → 40100 `backend/app/deps.py:74-78`；`backend/tests/test_admin.py::test_reset_password_invalidates_token_issued_before_reset:449`（重置前 token 访问 `/api/meta/units` → 401/40100） |
| TC-07 | 采购员看不到「账号管理」菜单，直接输 URL 后端返回 40300 | 已实现待验证 | pytest+前端功能 | 后端：`backend/app/deps.py:103-109`（require_admin → 40300）+ `backend/tests/test_admin.py::test_admin_apis_require_admin_and_pagination_works:691`；前端：`frontend/src/router/index.js:220-221`（按 `meta.roles` 拦截）、`frontend/src/router/menu.js:14`（按角色出菜单）；⚠「左侧无该菜单」需人工确认 |

### 2.2 询价单创建与导入（TC-08 ~ TC-15）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-08 | 新建草稿：表头填全 + 3 行明细保存，生成 `RFQ{yyyyMMdd}xxxx` 单号，列表状态草稿 | 已实现待验证 | pytest+前端功能 | 服务端：`backend/app/api/rfq.py:528-576`（create_rfq）、`backend/app/utils.py:52-69`（generate_rfq_no）；`backend/tests/test_rfq_flow.py::test_full_flow:22-26`（status=draft、`rfq_no.startswith("RFQ")`、3 行、2 家分派）；前端 `frontend/src/views/purchase/RfqEdit.vue`、`frontend/src/views/purchase/RfqList.vue`（整页，快照时 717 行）；⚠页面保存流程需人工 |
| TC-09 | 明细必填字段留空保存草稿：允许保存并给出非阻断提示 | 已实现待验证 | 代码审查+前端功能 | 服务端：`backend/app/api/rfq.py:663-694`（必填校验集中在 `_collect_publish_errors`，仅发布时执行，草稿不拦）；前端提示：`frontend/src/views/purchase/RfqEdit.vue:519-520,743-746`（`ElMessage.warning` + 警告条）；⚠提示形态需人工确认 |
| TC-10 | 未选供货商直接发布被阻断并提示「请至少选择一家供货商」 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/rfq.py:691`（期望文案）；`backend/tests/test_rfq_flow.py:54-60`；`scripts/e2e_acceptance.py` [3]:272-277 |
| TC-11 | 截止时间为过去时间时发布被阻断 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/rfq.py:670-672`（「报价截止时间：必须晚于当前时间」）；`backend/tests/test_rfq_flow.py:41-46`；`scripts/e2e_acceptance.py` [3]:278-280 |
| TC-12 | 下载模板 → 填 200 行 → 上传导入 → 确认，明细追加至 203 行 | 已实现待验证 | pytest+前端功能 | 服务端：`backend/app/api/rfq.py:382-401`（模板）、`:402-438`（预校验）、`:439-527`（确认）；追加模式断言 `backend/tests/test_importer.py:91-96`（`mode=append` → `total_lines`）；前端导入入口 `frontend/src/views/purchase/RfqEdit.vue:876-885`；⚠「200 行 → 203 行」规模场景需人工 |
| TC-13 | 上传含 5 处错误的模板：列出精确到行列的错误清单、可导出、未落库 | 已实现并通过 | pytest | `backend/tests/test_importer.py::test_errors_are_reported_by_row_and_column:38-72`（5 处错误 `(row, column)` 精确断言 + 「未落库：明细行数不变」）；未知单位 P1 选项 `backend/tests/test_importer.py::test_unknown_unit_skip_and_add:106-137`；接口 `backend/app/api/rfq.py:402` |
| TC-14 | 上传 `.xls`（`doc/示例.xls`）可正常读取 | 已实现并通过 | pytest | `backend/tests/test_importer.py::test_xls_ole2_compatibility_and_confirm:76-104`（读取 `doc/示例.xls` OLE2 并确认导入）；解析与格式回退 `backend/app/importer.py:185-203` |
| TC-15 | 导入第 2001 行：提示超过单次上限，要求分批 | 已实现并通过 | pytest | `backend/app/importer.py:237-239`（超限报错文案）；上限配置 `backend/app/config.py:48`（`import_max_rows = 2000`）；`backend/tests/test_importer.py:155-158`（「超过单次导入上限」） |

### 2.3 发布与分派（TC-16 ~ TC-20）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-16 | 发布成功：生成 5 条分派记录（pending）、单据转已发布、写发布日志 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/rfq.py:720-738`（分派 `status="pending"`、`rfq.status="published"`、`action=rfq.publish`）；`backend/tests/test_rfq_flow.py:81-85`；`scripts/e2e_acceptance.py` [3]:256-266 |
| TC-17 | 已发布单尝试增删改明细被拒（40900） | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/rfq.py:114-118`（`_load_draft` → 40900「已发布或已截止的询价单不可修改明细，请先撤回为草稿」）；`backend/tests/test_security.py::test_published_and_closed_guards:150-157`；`scripts/e2e_acceptance.py` [3]:268-270 |
| TC-18 | 撤回为草稿：二次确认、原报价保存为快照并作废、供货商侧该单消失 | 已实现待验证 | 代码审查+前端功能 | 服务端撤回：`backend/app/api/rfq.py:744-808`（仅 published 可撤回，`RfqSupplier` 置作废/清空）；前端二次确认入口 `frontend/src/views/purchase/RfqList.vue`；⚠**当前无自动化用例覆盖撤回**，「供货商侧消失」与快照内容需人工验证 |
| TC-19 | 已发布单无删除入口，接口返回 40900 | 已实现并通过 | pytest+代码审查 | `backend/app/api/rfq.py:622-645`（仅草稿可删；已发布/已截止 40900；有报价快照 40900）；`backend/tests/test_security.py:151`（断言删除返回 40900）；前端 `frontend/src/views/purchase/RfqList.vue` 仅草稿显示删除 |
| TC-20 | 报价进度：显示 3 家状态与未报价清单 | 已实现待验证 | e2e脚本+前端功能 | 服务端：`backend/app/api/rfq.py:839-850`（progress）；`scripts/e2e_acceptance.py` [3]:262-266；`backend/tests/test_rfq_flow.py:217-225`；前端 `frontend/src/views/purchase/RfqProgress.vue`（整页，快照时 754 行）；⚠页面展示需人工 |

### 2.4 供货商报价（TC-21 ~ TC-35）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-21 | 供货商只看到分派给本公司且已发布的单，看不到草稿单 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/supplier.py:190-192`（`supplier_id` 只取 token 身份 + `Rfq.status in ("published","closed")`）；`backend/tests/test_security.py::test_supplier_cannot_open_unassigned_rfq:57`；`scripts/e2e_acceptance.py` [4]:287-289；⚠UI 卡片渲染 `frontend/src/views/supplier/QuoteList.vue:5` 需人工 |
| TC-22 | 填报页物料列（序号/名称/规格/单位/数量）只读 | 已实现待验证 | 前端功能 | 服务端仅返回只读物料字段 `backend/app/schemas.py:447-459`（SupplierRfqLineOut）；前端 `frontend/src/views/supplier/components/MaterialCard.vue:182-184`（只读输入 `readonly tabindex="-1"`）、`frontend/src/views/supplier/components/QuoteTable.vue`；⚠需人工确认不可编辑 |
| TC-23 | 仅填 2/10 行保存：状态 partial、`quoted_line_count=2`、写 2 条改价历史（版本 1） | 已实现并通过 | pytest | `backend/app/api/supplier.py:250-355`（save_quotes + 历史写入）；`backend/tests/test_rfq_flow.py:121-135`（`my_status="partial"`、`quoted_line_count`、history `total==1`、`version==1`、`snapshot.price_incl_tax is None`）。说明：自动化以 1/3 行验证同一代码路径，「2 行 → 2 条历史」建议人工复跑 |
| TC-24 | 单价 100 改为 95：值更新、新增版本 2 历史、snapshot 记 100 且 `changed_fields` 含 `price_incl_tax` | 已实现并通过 | pytest | `backend/tests/test_rfq_flow.py:148-158`（`versions == [1, 2]`、`snapshot["price_incl_tax"] == "113.00"`、`changed_fields` 断言）；模型 `backend/app/models.py:242-258`（quote_history 只追加，无更新/删除入口） |
| TC-25 | 填满 10 行后提交：状态变 quoted；未截止时再次进入仍可修改 | 已实现并通过 | pytest | `backend/tests/test_rfq_flow.py:183-197`（`submit` → `my_status="quoted"`，再次读取 `readonly=False` 且可继续保存）；截止后转只读见 TC-30 |
| TC-26 | 仅填 9/10 行点提交被拒，提示第 10 行含税单价未填写 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/supplier.py:308-318`（未填行 → 400/40001「第N行 含税单价未填写」）；`backend/tests/test_rfq_flow.py:166-168`（「第2行 含税单价未填写」）；`scripts/e2e_acceptance.py` [4]:341-343 |
| TC-27 | 含税单价 113、税率 13% → 不含税单价自动 100.00 | 已实现并通过 | pytest+e2e脚本 | 计算 `backend/app/utils.py:37-49`（`calc_price_excl_tax`，ROUND_HALF_UP Decimal）；落库 `backend/app/api/supplier.py:338`；`backend/tests/test_rfq_flow.py:127`（`== "100.00"`）；`scripts/e2e_acceptance.py` [4]:320-326 |
| TC-28 | 含税开关选「否」时税率必填校验生效并阻断 | 已实现待验证 | 代码审查+前端功能 | 服务端：`backend/app/api/supplier.py:300-302`（`price_incl_tax` 有值且 `tax_included=False` 时必须有 `tax_rate`）；前端字段分组 `frontend/src/views/supplier/components/MaterialCard.vue:195-212`；⚠**无自动化用例**，建议补负向用例后人工复核 |
| TC-29 | 单价输入 -5 / abc：前端即时拦截；绕过前端后端返回 40001 | 已实现待验证 | 代码审查+前端功能 | 后端契约：`backend/app/schemas.py:364-368`（`price_incl_tax` `ge=0`、`le=9999999.99`）+ `backend/app/main.py:84-96`（RequestValidationError → 40001）；前端输入类型 `frontend/src/views/supplier/components/MaterialCard.vue:120,195`（`inputmode="decimal"`）；⚠无自动化负向用例，需人工 |
| TC-30 | 截止后填报页只读、输入禁用，保存接口返回 40301 | 已实现并通过 | pytest | `backend/app/api/supplier.py:261`（403/40301「报价已截止，无法修改」）；只读判定 `backend/app/api/supplier.py:153`（closed 或 已过截止）；`backend/tests/test_security.py::test_published_and_closed_guards:159-170`（40301 + `readonly is True`）；⚠UI 禁用态：`frontend/src/views/supplier/QuoteFill.vue:674`（截止后替换为说明条）需人工 |
| TC-31 | 供货商 A 调用他方报价接口：40300 并记录越权告警日志 | 已实现并通过 | e2e脚本 | 我方接口守卫 `backend/app/api/rfq.py:70-85`（`require_internal_audited`，40300 + 留痕）；越权留痕工具 `backend/app/deps.py:134-156`（`audit_forbidden` → `action="security.forbidden"`）；`scripts/e2e_acceptance.py` [4]:349-355（断言存在 `security.forbidden` 日志） |
| TC-32 | 供货商调用报表接口 `/api/reports/rfq-comparison`：40300 | 已实现并通过 | pytest+e2e脚本 | `backend/app/api/report.py:42-57`（`require_report_access` → `audit_forbidden`）；`backend/tests/test_security.py::test_supplier_cannot_access_reports:25`；`scripts/e2e_acceptance.py` [4]:346-347 |
| TC-33 | 供货商 A 与 B 并发保存同一单据不同行，互不覆盖 | 已实现并通过 | pytest+代码审查 | 乐观锁：`backend/app/api/supplier.py:264-269`（`expected_updated_at` 不符 → 409/40900）；行隔离：`backend/app/models.py:213-217`（`uq_quote_line(rfq_supplier_id, line_uid)`，不同供货商的报价行物理隔离）；`backend/tests/test_security.py::test_optimistic_lock_conflict:173-195` |
| TC-34 | 供货商 A 打开 B 公司分派的单据 ID：40300（服务端按 supplier_id 校验） | 已实现并通过 | pytest | `backend/app/api/supplier.py:106-129`（`_load_assignment`：无分派/非本公司 → `audit_forbidden`）；`backend/tests/test_security.py::test_supplier_cannot_open_unassigned_rfq:57-77` |
| TC-35 | 上传 20MB 的 exe：按类型/大小被拒 | 已实现并通过 | pytest | `backend/app/api/supplier.py:475-490`（扩展名白名单 + 大小上限，400/40001）；配置 `backend/app/config.py:45`（`max_upload_size_mb=10`）、`backend/app/config.py:68`（`allowed_upload_ext`）；`backend/tests/test_security.py::test_attachments_whitelist_and_isolation:198-216`（exe 被拒、超限被拒、跨供货商下载 403） |

### 2.5 统计报表（TC-36 ~ TC-41）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-36 | 视图 A：3 个供货商列、未报价显示「—」，最低价/最高价/均价/价差率正确 | 已实现待验证 | pytest+前端功能 | 计算：`backend/app/api/report.py:94-206`（`build_comparison`，含 `diff_rate`）；精确数值断言 `backend/tests/test_rfq_flow.py:231-238`（best 95.00 / max 100.00 / avg 97.50 / best_supplier_name）；前端列与「—」渲染、`bestWins` 高亮 `frontend/src/views/purchase/RfqReport.vue:117-121`；⚠需人工核算比对 |
| TC-37 | 按最低价排序，最低价行高亮 | 已实现待验证 | 前端功能 | 接口返回完整数据由前端排序：`backend/app/api/report.py:207-224`（无排序参数）；前端排序 `frontend/src/views/purchase/RfqReport.vue:138-139`（`compare.sort`）、高亮 `:117-121`、`:950`（hover 样式）；⚠需人工 |
| TC-38 | 供货商刚保存报价，我方刷新报表数据立即可见（无缓存延迟） | 已实现并通过 | pytest+代码审查 | 服务端无任何缓存，每次请求实时 `build_comparison`：`backend/app/api/report.py:207-224`、`:94-206`；`backend/tests/test_rfq_flow.py:228-238`（提交报价后立即读取并断言最新价 `95.00`）；⚠浏览器端刷新体验需人工 |
| TC-39 | 筛选「最近 30 天」：视图 B 指标与手工核算一致，金额两位小数带 ¥ | 已实现待验证 | pytest+前端功能 | 时间范围解析 `backend/app/api/report.py:256-263`（`_resolve_range`）；汇总计算 `backend/app/api/report.py:264-450`、接口 `:451-481`；大单正确性/性能 `backend/tests/test_perf.py::test_summary_is_fast_on_large_rfq:149-164`（`line_count`/`invited_assignments` 断言 + 计算耗时预算）；¥ 格式化 `frontend/src/composables/useFormat.js:23-24`；⚠「与手工核算一致」需人工 |
| TC-40 | 无任何报价的单据打开视图 A：明确空状态提示，不报错不白屏 | 已实现待验证 | 前端功能 | 服务端空数据安全返回（rows=[]）：`backend/app/api/report.py:94-206`；前端空状态组件 `frontend/src/components/AppStatePage.vue`、`frontend/src/views/purchase/RfqReport.vue`；⚠需人工构造无报价单据验证 |
| TC-41 | 报表页导出 .xlsx：可打开、数据与页面一致、文件名符合 `询价单_{单号}_{项目}_{日期}.xlsx` | 已实现待验证 | e2e脚本+代码审查 | 导出路由 `backend/app/api/report.py:225-255`（视图 A）、`:482-528`（视图 B）；文件名规范化 `backend/app/exporter.py:61-75`（`询价单_…`/`比价明细_…`/`报价单统计_…` + RFC5987 Content-Disposition）；xlsx 有效性（PK 魔数）`scripts/e2e_acceptance.py` [5]:383-397；⚠页面导出按钮与打开效果需人工 |

### 2.6 日志（TC-42）

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-42 | 登录/新建单/发布/供货商提交报价/导入账号均有日志（时间、操作人、角色、动作、IP），且无删除入口 | 已实现并通过 | pytest+curl手工 | 只读查询接口 `backend/app/api/admin.py:1637-1690`（返回 `operator_name/role/action/target_type/target_id/summary/client_ip/created_at`）；动作类型清单 `frontend`/接口 `/audit-logs/actions`；无删除能力 `backend/tests/test_admin.py::test_accounts_and_audit_logs_are_not_deletable:389`（DELETE → 404/405）；真实日志样例 `backend/data/test_artifacts/verify_audit_logs.txt`、`backend/data/test_artifacts/curl_audit_logs.txt`；`scripts/e2e_acceptance.py` [6]:414-418；⚠日志页已交付：`frontend/src/views/system/AuditLog.vue:6`（「日志只读…无删除入口」）、`:14-15`（筛选接口）、`:101-103`（动作类型元数据）；界面查询与筛选需人工走查 |

### 2.7 移动端与响应式（TC-43 ~ TC-67）—— **必须在真实设备执行**

> PRD L967、L1043：11.7 节共 25 条，**模拟器结果不作为通过依据**；真机矩阵见 PRD 10.6。
> 本节 25 条状态一律为「已实现待验证」，验证方式为「前端功能（真机）」；证据为前端实现位置，**不代表已通过**。

| 用例号 | 用例要点 | 实现状态 | 验证方式 | 证据位置 |
|---|---|---|---|---|
| TC-43 | iPhone Safari 登录页单列居中；聚焦不自动放大；键盘不遮挡按钮 | 已实现待验证 | 前端功能 | `frontend/index.html:11`（`viewport-fit=cover`，防放大基线）、`:14-15`（apple-touch-icon/manifest）；登录页 `frontend/src/views/Login.vue:90-101`；安全区 `frontend/src/styles/index.scss:149`、`frontend/src/layouts/AdminLayout.vue:374`；**需 iPhone 真机** |
| TC-44 | 手机端首次登录 → 跳改密页 → 改密后进入待报价列表 | 已实现待验证 | 前端功能 | 改密页 `frontend/src/views/ChangePassword.vue:1-334`（含 pwd 校验与 API 调用）；列表 `frontend/src/views/supplier/QuoteList.vue`（整页，快照时 704 行）；**需真机** |
| TC-45 | 待报价列表卡片展示名称/项目/剩余时间/我的状态 x/y，无横向滚动 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/QuoteList.vue:5`（手机端卡片列表说明）、`:19-28`（状态徽标）、`:107-112`（pending/quoted 计数）、`:122`（剩余时间文案） |
| TC-46 | 剩余时间 < 24h 以醒目色呈现 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/QuoteList.vue:122`（剩余时间文案）；`frontend/src/views/supplier/QuoteFill.vue:166-172`（`urgent` 计算，≤24h）；顶栏徽标色 `QuoteFill.vue:170-181`（`appBarBadge`/`appBarBadgeTone`，danger 态） |
| TC-47 | 竖屏填报页每行一张卡片，默认只展开「含税单价」，无横向滚动 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/components/MaterialCard.vue:7-8`（默认展开项与折叠项）、`:111-124`（含税单价独占一行） |
| TC-48 | 点击单价弹出含小数点的数字键盘，输入 113.50 正常 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/components/MaterialCard.vue:120`（`inputmode="decimal"`）、`:195`（税率 decimal）、`:212`（天数 numeric）；`QuoteTable.vue:137,181,195` |
| TC-49 | 底部固定栏显示「已填 3/10 行」，保存/提交在任意滚动位置可达且不被 iPhone 底部横条遮挡 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/QuoteFill.vue:674`（`<StickyBar>`）、`:493,732` 同文件 `has-bottombar` 预留高度；`frontend/src/components/StickyBar.vue:3-16,103`（`position: fixed` + `env(safe-area-inset-bottom)`） |
| TC-50 | 「更多报价信息」展开后每个字段独占一行，标签在输入框上方，无挤压换行 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/components/MaterialCard.vue:8`（折叠字段清单）、`:182-229`（不含税单价/MOQ/交期/到货日期/备注逐行） |
| TC-51 | 点击「相机」直接调起系统相机，拍照方向正常，上传后显示缩略图 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/components/AttachmentPicker.vue:6-7`（`capture="environment"` / 相册双入口）、`:276`（file input）；**EXIF 方向必须真机确认（模拟器不算）** |
| TC-52 | 8MB 手机原图压缩至 ≤2MB 后上传成功，页面不卡死 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/composables/useImageCompress.js:14-16`（`IMAGE_MAX_EDGE=1920`/`QUALITY=0.8`/`MAX_BYTES=2MB`）、`:54-115`（canvas 压缩）；接线 `AttachmentPicker.vue:12` |
| TC-53 | 已填 9/10 行点提交：弹出确认并指出第 N 行未填，阻断提交 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/quoteModel.js:426`（`validateForSubmit`）；`frontend/src/views/supplier/components/SubmitConfirmSheet.vue:6,77,81,95`（未填行阻断，不渲染确认按钮） |
| TC-54 | 已填 10/10 行提交成功：Toast 提示成功、状态更新为已报价、提示截止前仍可修改 | 已实现待验证 | 前端功能 | `frontend/src/views/supplier/QuoteFill.vue:358`（「报价已提交成功，截止前仍可修改」）；Toast 组件 `frontend/src/views/supplier/components/SupplierToast.vue`；顶栏状态 `QuoteFill.vue:174-180` |
| TC-55 | 弱网/断网保存：15s 内失败提示 + 「重试」，已填内容不清空，恢复网络后重试成功 | 已实现待验证 | 前端功能 | 超时 15s `frontend/src/views/supplier/quoteModel.js:45`（`QUOTE_REQUEST_TIMEOUT=15000`）；失败保留与重试 `QuoteFill.vue:320-324`（FR-RWD-23 注释）、`:307-322`（错误分支）、`:565-590`（错误条 + 重试/覆盖按钮模板）；附件重试 `AttachmentPicker.vue:184,192,269`；**需真机弱网验证** |
| TC-56 | 填报中途切后台再返回：内容仍在；超时提示「检测到未保存草稿，是否恢复」 | 已实现待验证 | 前端功能 | 草稿读写 `frontend/src/views/supplier/quoteModel.js:464-505`（`draftKey`/`toDraft`/`draftHasContent`/`applyDraft`）、`QuoteFill.vue:189`（「检测到未提交的草稿，保存于 …」）、`:214-262`（`readDraft`/`persistDraft`/`restoreDraft`/`dismissDraft`，localStorage） |
| TC-57 | 供货商手机端直接输 URL 访问 `/purchase/rfq` 或 `/system/account`：被拦截或 40300，无数据泄露 | 已实现待验证 | 前端功能+pytest | 前端路由守卫 `frontend/src/router/index.js:172-220`（`beforeEach` 校验 `meta.roles`，`:217-218`）；后端兜底 40300 `backend/app/deps.py:103-109` + `backend/tests/test_admin.py:691`；⚠需真机确认无泄露 |
| TC-58 | Android Chrome 询价单列表：表格转卡片、筛选收进抽屉、分页热区 ≥44px、无横向溢出 | 已实现待验证 | 前端功能 | 双形态封装 `frontend/src/components/DataTable.vue:6-7`（<768px 卡片 / ≥768px 表格）；筛选抽屉 `frontend/src/views/purchase/RfqList.vue:338-378` + `frontend/src/components/FilterDrawer.vue:3-10`；热区 `RfqList.vue:630,713`（`min-height: touch-target`） |
| TC-59 | 手机端报表：视图 B 指标卡单列可读；视图 A 紧凑表格横向滚动且首列冻结，数据与 PC 一致 | 已实现待验证 | 前端功能 | 仅横向滚动容器 `frontend/src/views/purchase/RfqReport.vue:494`（`xj-hscroll`）、`:883-889`（注释「手机端唯一允许的横向滚动形态」）；首列冻结 `:498,520`（`sticky-col`）、`:933-941`（`position: sticky`）；指标卡见同文件 view=summary 分支 |
| TC-60 | 手机端新建询价单页：导入等重入口隐藏或提示电脑操作；表单可填、发布按钮吸底可达 | 已实现待验证 | 前端功能 | `frontend/src/views/purchase/RfqEdit.vue:519-520`（`ElMessage.warning('Excel 导入仅桌面端提供，建议使用电脑操作')`）、`:743-746`（「建议在电脑上创建询价单」提示条）、`:876-885`（仅 `!isMobile` 渲染导入与明细入口）、`:1104`（手机端 `<StickyBar>` 吸底） |
| TC-61 | 微信（iOS/Android）内完成登录→列表→填报→保存；点导出提示「请在系统浏览器打开下载」 | 已实现待验证 | 前端功能 | 下载实现 `frontend/src/api/request.js:270-319`（Blob + `link.download`）；⚠**未在代码中定位到「微信内请用系统浏览器打开下载」的提示实现**（grep `微信`/`microMessenger`/`系统浏览器` 于 `frontend/src` 无命中），需人工确认是否缺失；**必须真机（微信内置浏览器）** |
| TC-62 | iPad 竖屏/横屏旋转后布局在 768~1199px 档正确切换，无截断与滚动位置异常 | 已实现待验证 | 前端功能 | 断点定义 `frontend/src/composables/useBreakpoint.js:4-6,19`（768/1200）；平板形态 `frontend/src/components/DataTable.vue:6-7`、`frontend/src/layouts/AdminLayout.vue`；**需 iPad 真机** |
| TC-63 | 系统字号放大至 130%：登录页/待报价列表/填报页不错乱、不截断、底部栏不遮挡 | 已实现待验证 | 前端功能 | 输入字号基线 16px `frontend/src/views/supplier/components/MaterialCard.vue:591`、`QuoteTable.vue:427`；底部栏安全区 `frontend/src/components/StickyBar.vue:103`、`QuoteFill.vue:732`；**需真机调整系统字号** |
| TC-64 | PC Chrome 宽度 1920→375：在 1200/768 两断点平滑切换，全程无横向滚动与重叠 | 已实现待验证 | 前端功能 | 断点 `frontend/src/composables/useBreakpoint.js:19`；双布局 `frontend/src/layouts/AdminLayout.vue:374`、`frontend/src/layouts/SupplierLayout.vue:105,170`；双形态表格 `frontend/src/components/DataTable.vue:6-7` |
| TC-65 | 供货商 10 行物料、4G 网络冷启动填报页：首屏可交互 ≤3s，滚动流畅 | 已实现待验证 | 前端功能 | 骨架屏 `frontend/src/views/supplier/QuoteFill.vue:496-499`（首屏占位，减少白屏）；列表懒加载 `frontend/src/router/index.js:10,19-21`（路由级 `() => import`）；**需真机 4G 实测**（性能预算见 PRD 8） |
| TC-66 | 43 行物料按每 10 行分段（「第 1~10 行 / 共 43 行」），切换分段不丢内容，底部「已填 x/43」按整单统计 | 已实现待验证 | 前端功能 | 分段实现 `frontend/src/views/supplier/quoteModel.js:28`（`SEGMENT_SIZE=10`）、`:357-390`（`buildSegments`/`segmentUnfilledCount`）；页面接线 `frontend/src/views/supplier/QuoteFill.vue:138`（`useSegments`：>10 行才分段）、`:587-630`（分段导航模板「第 x~y 行 / 共 N 行」）、`:674`（底部栏按整单「已填 x/总数」） |
| TC-67 | 手机端填写「到货日期」（Q12 定稿：原生 `date` 控件）可正常选择保存，不被键盘/底部栏遮挡、无超宽面板 | 已实现待验证 | 前端功能 | 原生 `date` 控件 `frontend/src/views/supplier/components/MaterialCard.vue:8,229`（`type="date"`）；日期范围约束 `frontend/src/views/supplier/quoteModel.js:159-170`（`localDateISO`/`arrivalMaxDate`）；**需真机确认 iOS 原生控件不被底部栏遮挡** |

---

## 3. 统计与自检

- TC 行数：**67**（`grep -c '^| TC-' doc/ACCEPTANCE-MATRIX.md` → 67，见第 5 节自检命令）。
- 每行「证据位置」均非空，且指向真实文件行号 / 测试函数 / 产物路径 / 脚本分节。
- 「已实现并通过」的 27 条：TC-01、TC-02、TC-04、TC-05、TC-06、TC-10、TC-11、TC-13、TC-14、TC-15、TC-16、TC-17、TC-19、TC-21、TC-23、TC-24、TC-25、TC-26、TC-27、TC-30、TC-31、TC-32、TC-33、TC-34、TC-35、TC-38、TC-42。
- 「已实现待验证」的 40 条：TC-03、TC-07、TC-08、TC-09、TC-12、TC-18、TC-20、TC-22、TC-28、TC-29、TC-36、TC-37、TC-39、TC-40、TC-41、TC-43 ~ TC-67（移动端 25 条）。

---

## 4. 汇总清单

### 4.1 本期明确未做（对照 PRD 1.3 排除项与 Q 系列）

| 项 | 来源 | 说明 / 原因 |
|---|---|---|
| 邮件 / 短信 / 站内消息通知 | PRD L51 | 需求方明确排除；供货商登录后自行看到待报价 |
| 询价单审批流、多级会签 | PRD L52 | 明确排除 |
| 多轮议价状态机 | PRD L53 | 明确排除；仅保留改价历史（TC-24 已覆盖） |
| 定标 / 下单 / 合同 / 收货 / 对账 / 付款 | PRD L54 | 明确排除 |
| 物料主数据库、供应商准入与评价 | PRD L55 | 明确排除（明细行物料为手工录入/Excel 导入） |
| ERP / OA 对接 | PRD L56 | 明确排除 |
| 原生 App（iOS/Android）与微信小程序 | PRD L57 | 明确排除；本期只做同一套 Web 的响应式适配（TC-43~67 即为该范围的验收） |
| 扫码入库、拍照 OCR、语音录入、电子签名、离线填报（断网提交） | PRD L58 | 明确排除；弱网仅做「不清空 + 重试」（TC-55） |
| 小程序登录与分享 | PRD L59 | 明确排除 |
| Service Worker 离线缓存 | PRD L830 | 明确排除；仅做 `manifest.json` + `apple-touch-icon`（Q9 按建议执行，Q11 机型清单未提供，影响真机验收范围） |
| 催办一键拨号/发短信（Q10） | PRD L1106 | 按建议只做「复制供货商名称与电话」，不做短信集成（与「不做通知」一致） |

> 说明：以上均为**范围排除**，在 TC-01~TC-67 中没有对应验收用例，因此矩阵中「未实现（本期排除）」计数为 0。

### 4.2 需在真实手机上人工验证项（TC-43 ~ TC-67，共 25 条）

> 前置：`bash scripts/dev-all.sh` 或前端 `npm run dev` + 后端 uvicorn；手机与电脑同一内网，访问 `http://<电脑IP>:<端口>`。
> 设备矩阵（PRD 10.6）：**≥1 台 iPhone（iOS Safari ≥16）+ ≥1 台 Android（Chrome ≥110）**；模拟器结果不作为通过依据（PRD L472/FR-RWD-30）。

| 用例 | 操作步骤简述 | 重点确认 |
|---|---|---|
| TC-43 | iPhone Safari 打开登录地址 → 点用户名/密码输入框 | 单列居中；**聚焦不放大**；键盘弹出时登录按钮可见可点 |
| TC-44 | 用供货商初始密码登录 → 改密 → 进入待报价列表 | 强制跳改密页；改密后能进入列表 |
| TC-45 | 打开待报价列表（≥2 张单） | 卡片含名称/项目/剩余时间/我的状态 x÷y；**无横向滚动条** |
| TC-46 | 造一张剩余 <24h 的单，查看该卡片 | 剩余时间呈醒目色（橙/红） |
| TC-47 | 打开 10 行物料的填报页，竖屏看首屏 | 一行一卡；默认只展开「含税单价」；规格/单位/数量为次要信息；无横向滚动 |
| TC-48 | 点单价输入框 | 数字键盘**含小数点**；输入 113.50 正常 |
| TC-49 | 填 3/10 行，滚动页面 | 底部栏常显「已填 3/10 行」；保存/提交在任意位置可达；**iPhone 上不被底部横条遮挡** |
| TC-50 | 展开任一行的「更多报价信息」 | 税率/MOQ/交期/到货日期/备注/附件各占一行，标签在输入框上方 |
| TC-51 | 点附件「相机」→ 拍照 → 上传 | 直接调起相机；**照片方向正常（无 EXIF 旋转）**；上传后显示缩略图 |
| TC-52 | 上传一张 8MB 手机原图 | 压缩至 ≤2MB 后上传成功；页面不卡死 |
| TC-53 | 填 9/10 行点「提交报价」 | 弹出确认并指出第 N 行未填；**阻断提交** |
| TC-54 | 填满 10/10 行点「提交报价」 | Toast 成功提示；状态变已报价；提示「截止前仍可修改」 |
| TC-55 | 限速至 2G/断网后点「保存」；再恢复网络点「重试」 | 15s 内失败提示 + 重试按钮；**已填内容不被清空**；恢复后重试成功 |
| TC-56 | 填报中切到后台/其他 App 再切回；另测超会话时间场景 | 已填内容仍在；超时后提示「检测到未保存草稿，是否恢复」 |
| TC-57 | 用供货商账号在手机浏览器直接输 `…/purchase/rfq` 与 `…/system/account` | 被路由守卫拦截或后端 40300；**无任何我方数据泄露** |
| TC-58 | Android Chrome 打开询价单列表（窄屏） | 表格转卡片；筛选进「筛选」抽屉；分页热区 ≥44px；无横向溢出 |
| TC-59 | 手机打开统计报表（视图 A 与 B） | 视图 B 指标卡单列可读；视图 A 紧凑表格可横向滚动且**首列冻结**；与 PC 数据一致 |
| TC-60 | 手机打开新建询价单页 | Excel 导入/批量粘贴入口隐藏或提示「建议使用电脑操作」；表单可填；发布按钮吸底可达 |
| TC-61 | 在微信（Android + iOS）内打开系统，走完 登录→列表→填报→保存，并点一次导出 | 全流程可用；数字键盘/滚动/拍照正常；导出时提示「请在系统浏览器打开下载」 |
| TC-62 | iPad 竖屏 ↔ 横屏旋转，逐页检查 | 768~1199px 档正确切换；旋转后无内容截断、无滚动位置异常 |
| TC-63 | 手机系统字号调至 130%，检查登录页/待报价列表/填报页 | 布局不错乱、文字不截断、底部栏不遮挡内容 |
| TC-64 | PC Chrome 窗口从 1920 逐步缩小到 375 | 在 1200 / 768 断点平滑切换；**全程无横向滚动条**（表格内部除外）、无元素重叠 |
| TC-65 | 供货商 10 行物料、4G 网络，冷启动打开填报页并滚动 | 首屏可交互 ≤3s；滚动流畅无明显掉帧 |
| TC-66 | 打开 43 行物料的填报页，切分段并填若干行 | 显示「第 1~10 行 / 共 43 行」；切换分段**已填内容不丢**；底部「已填 x/43」按整单统计 |
| TC-67 | 手机端填写「到货日期」（原生 date 控件） | 能正常选择并保存；**不被键盘/底部栏遮挡**、无超宽面板溢出 |

### 4.3 已知限制与风险

| 类别 | 内容 | 证据 / 影响 |
|---|---|---|
| 前端页面未人工走查 | 生成期间 8 个页面仍是 `fe-base-placeholder` 占位页，至快照时点已全部交付，但尚无任何人工功能走查记录；`frontend/dist/` 为交付前构建，页面改动后需重新构建 | 涉及 TC-03、TC-07~TC-09、TC-12、TC-18、TC-20、TC-22、TC-28、TC-29、TC-36~TC-41、TC-42 界面部分及 TC-43~TC-67 全部；矩阵中已按「已实现待验证」处理 |
| 移动端真机未验证 | 25 条真机专项尚未执行；模拟器结果不作为通过依据（PRD L472 / FR-RWD-30） | 第 4.2 节清单；上线前为阻断项 |
| TC-61 实现缺口待确认 | 代码中未定位到「微信内请用系统浏览器打开下载」的提示实现（grep `微信`/`microMessenger`/`系统浏览器` 无命中） | `frontend/src/api/request.js:270-319` 仅做 Blob 下载；需人工确认是否缺失并补齐 |
| 导入 token 存于进程内存 | 30 分钟有效、一次性；多 worker / 多实例部署需迁移 Redis 或数据库表 | `backend/app/api/admin.py:1-20`（模块 docstring 已注明限制）；当前单 worker 无影响 |
| 自动截止为惰性触发 | 无后台扫描线程；`auto_close_if_due` 在读取单据/保存报价时触发，`config.auto_close_scan_seconds` 目前未被任何调度使用 | `backend/app/api/rfq.py:109,319`、`backend/app/api/supplier.py:239-241`、`backend/app/utils.py:127-143`、`backend/app/config.py:50`；长时间无人访问时列表状态可能滞后到下次读取 |
| SQLite 并发写 | 已开 WAL + `busy_timeout=15s`；供货商规模增长后建议切 PostgreSQL（compose 已提供 profile） | `backend/app/database.py:48-60`、`README.md:155` |
| 数据库迁移脚本未落地 | PRD 非功能要求 Alembic；当前原型阶段用 `create_all`，仓库内无 alembic 目录 | `backend/app/database.py:78-83`（代码注释已说明） |
| 导出无行数上限 | 供货商账号清单 / 报表导出均为一次性全量导出，未设 `export_max_rows` 守卫（数据量级：内网 20 人、供货商数十家，经评估暂不加） | 决策记录见 task-7 验收结论；潜在风险为供货商量级上千时内存/耗时 |
| 无消息通知 | 按需求不做邮件/短信，催办依赖「报价进度」页 | `README.md:156`、PRD L51 |
| 前端未引入 TypeScript / ESLint | 体量小、单人开发，未做静态检查工具链 | `README.md:157` |
| 未提供机型清单（Q11） | 需求方尚未提供指定机型，真机验收范围待定 | PRD L1107 |

---

## 5. 自检命令（可复跑，验证本矩阵自身的完整性）

```bash
# 1) 矩阵用例行数必须为 67（只统计含「实现状态」列的 5 列行；第 4.2 节的真机清单行不计入）
grep -cE '^\| TC-[0-9]{2} \|.*\| (已实现并通过|已实现待验证|未实现（本期排除）|不适用) \|' doc/ACCEPTANCE-MATRIX.md
# 期望输出 67

# 2) 各状态条数（期望 27 / 40 / 0 / 0）
for s in 已实现并通过 已实现待验证 '未实现（本期排除）' 不适用; do
  printf '%s: ' "$s"
  grep -E "^\| TC-[0-9]{2} \|.*\| $s \|" doc/ACCEPTANCE-MATRIX.md | wc -l
done

# 3) 编号连续且不漏（应无 MISSING 输出）
for i in $(seq -w 1 67); do grep -q "^| TC-$i |" doc/ACCEPTANCE-MATRIX.md || echo "MISSING TC-$i"; done

# 4) 证据位置列不得为空（应无输出）
grep -nE '^\| TC-[0-9]{2} \|.*\| +\| *$' doc/ACCEPTANCE-MATRIX.md

# 5) 后端自动化证据可复跑
cd backend && ./.venv/Scripts/python.exe -m pytest tests -q          # 生成时点：29 passed
bash ../scripts/e2e-acceptance.sh                                    # 端到端闭环（需要后端已启动）

# 6) 关键证据行号抽检（行号随代码变更需重新核对）
sed -n '179,204p' backend/app/api/admin.py        # _guard_last_admin（FR-ACC-06）
sed -n '263p'     backend/app/api/supplier.py     # 40301 报价已截止
sed -n '687p'     backend/app/api/rfq.py          # 发布前「请至少选择一家供货商」
sed -n '61,75p'   backend/app/exporter.py         # 导出文件命名规范
```
