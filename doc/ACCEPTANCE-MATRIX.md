# PRD 验收矩阵（TC-01 ~ TC-67）

> 依据：`doc/PRD-询价报价系统.md` 第 11 章「验收用例」（逐条抄录，未凭记忆）。
> **状态复核：2026-10-24**。当前 67 条：**27 已实现并通过 / 40 已实现待验证 / 0 未实现 / 0 不适用**。
> 本文件只记「TC → 状态 + 证据」，不写"未做清单/真机步骤/已知限制"——那些在 `doc/TODO.md` 与 `doc/README`，避免两处口径。
> 证据中的**行号**是复核时点的实际行号，代码改动后需重新核对。

---

## 1. 交付结论（覆盖统计）

| 实现状态 | 条数 | 占比 | 说明 |
|---|---|---|---|
| 已实现并通过 | 27 | 40.3% | 用例中可机检的核心行为（错误码 / 数据 / 文件 / 日志）已被自动化测试（pytest、e2e 脚本）或留存产物覆盖 |
| 已实现待验证 | 40 | 59.7% | 核心验收点落在页面交互 / 视觉 / 真机，或需人工比对；其中 25 条为 PRD 强制真机专项 |
| 未实现（本期排除） | 0 | 0% | 67 条用例均在范围内；PRD 1.3 排除项没有对应验收用例（清单见第 4.1 节） |
| 不适用 | 0 | 0% | — |
| **合计** | **67** | 100% | — |

**当前自动化基线**：`pytest tests/` = **57 passed**（11 个测试文件，含数据隔离 6 条、需求变更 10 条）；
端到端 `scripts/e2e_acceptance.py` = **47 通过 / 0 失败 / 1 跳过**；移动端元素级
`scripts/mobile-acceptance.sh` = 6 页通过。前端 10 个页面均已交付并做过浏览器实测（桌面 + 375px），
但凡"预期结果含页面交互/视觉/真机"的用例仍按判定口径标记「已实现待验证」，不因人工走过一次就标通过。

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

> 为避免与 TODO 重复，本节只保留指针：

| 想知道 | 去处 |
|---|---|
| 本期**明确不做**的项与原因 | [TODO.md](TODO.md) §1（`TODO-001`~`TODO-016`） |
| 需在**真实设备**人工验证的 25 条（TC-43~TC-67）操作分组与环境 | [TODO.md](TODO.md) §2 |
| 已知限制与风险（时区、多 worker、SQLite、机型清单等） | [TODO.md](TODO.md) §3、[../README.md](../README.md)「已知问题」 |
| 已完成的历史事实核对（3 项此前记录有误，已在 2026-10-24 纠正） | 见下 |

**2026-10-24 复核纠正的 3 条旧结论**（原文曾记为本矩阵"已知限制"，实际已实现）：

| 旧结论 | 实际情况 | 证据 |
|---|---|---|
| TC-61「微信内提示改用系统浏览器」未实现 | **已实现** | `frontend/src/api/request.js:299-306`（`MicroMessenger` 检测 + 提示） |
| 自动截止只有惰性触发、无后台扫描 | **已有后台定时扫描**（每 `auto_close_scan_seconds` 秒） | `backend/app/services/scheduler.py:56`、`backend/app/config.py:50` |
| 导出无行数上限 | **已有上限守卫** | `backend/app/api/rfq.py:1048-1052`（`export_max_rows`） |

## 5. 自检命令（可复跑，验证本矩阵自身的完整性）

> 注意：本文件**不含**真机清单表格（已迁至 TODO §2），因此下面统计的人数应恰为 67。

```bash
# 1) 用例行数必须为 67
grep -cE '^\| TC-[0-9]{2} \|' doc/ACCEPTANCE-MATRIX.md          # 期望 67

# 2) 各状态条数（期望 27 / 40 / 0 / 0）
for s in 已实现并通过 已实现待验证 '未实现（本期排除）' 不适用; do
  printf '%s: ' "$s"
  grep -E "^\| TC-[0-9]{2} \|.*\| $s \|" doc/ACCEPTANCE-MATRIX.md | wc -l
done

# 3) 编号连续且不漏（应无 MISSING 输出）
for i in $(seq -w 1 67); do grep -q "^| TC-$i |" doc/ACCEPTANCE-MATRIX.md || echo "MISSING TC-$i"; done

# 4) 证据位置列不得为空（应无输出）
grep -nE '^\| TC-[0-9]{2} \|.*\| +\| *$' doc/ACCEPTANCE-MATRIX.md

# 5) 自动化证据可复跑
cd backend && ./.venv/Scripts/python.exe -m pytest tests -q          # 期望 57 passed
cd .. && ./backend/.venv/Scripts/python.exe scripts/e2e_acceptance.py # 期望 47 通过 / 0 失败（需后端已启动）

# 6) 关键证据行号抽检（行号随代码变更需重新核对）
sed -n '1048,1052p' backend/app/api/rfq.py         # export_max_rows 导出上限
sed -n '299,306p'   frontend/src/api/request.js    # 微信内置浏览器下载提示（TC-61）
sed -n '50,60p'     backend/app/services/scheduler.py  # 自动截止后台扫描
```
