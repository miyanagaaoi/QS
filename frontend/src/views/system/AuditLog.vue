<script setup>
/**
 * AuditLog — 系统管理 · 操作日志（PRD 5.4.4 / FR-LOG-01~04，设计稿 04-4）
 * ---------------------------------------------------------------------------
 * 硬约束：
 *  1. **日志只读，任何角色（含管理员）都没有删除入口** —— 页头/表上/表下三处明示，
 *     并且本页面不渲染任何删除或清理按钮（后端也没有删除接口）；
 *  2. 筛选：时间范围（date_from / date_to，含当天）、操作人（姓名/用户名/ID 模糊）、动作类型；
 *  3. 表格字段：时间 / 操作人 / 角色 / 动作类型 / 目标对象与摘要 / 客户端 IP；
 *  4. 手机端转卡片列表（FR-RWD-03）；
 *  5. 导出：后端未提供日志导出接口 → 前端 CSV 兜底（带 BOM，Excel 可直接打开），
 *     导出内容为**当前筛选条件下的全部记录**（分批拉取，最多 5000 条）。
 *
 * 接口（实测）：GET /admin/audit-logs?page&page_size&date_from&date_to&operator&action&target_type
 *              GET /admin/audit-logs/actions
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import DataTable from '@/components/DataTable.vue'
import FilterDrawer from '@/components/FilterDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatDateTime } from '@/composables/useFormat'

import * as api from './adminApi'

defineOptions({ name: 'SystemAuditLog' })

const { isMobile } = useBreakpoint()

const MAX_EXPORT_ROWS = 5000
const EXPORT_PAGE_SIZE = 200

const state = reactive({
  loading: false,
  rows: [],
  page: 1,
  pageSize: 20,
  total: 0,
  exporting: false,
  query: { range: [], operator: '', action: '' },
})

const actionOptions = ref([])

/** 动作类型 → 中文标签 + 语义色（顺序即设计稿"动作类型"列的口径） */
const ACTION_META = {
  'auth.login': { label: '登录', tone: 'muted' },
  'auth.logout': { label: '退出登录', tone: 'muted' },
  'auth.login_failed': { label: '登录失败', tone: 'danger' },
  'auth.change_password': { label: '修改密码', tone: 'info' },
  'security.forbidden': { label: '越权访问', tone: 'danger' },
  'rfq.create': { label: '询价单新建', tone: 'warn' },
  'rfq.update': { label: '询价单修改', tone: 'warn' },
  'rfq.publish': { label: '询价单发布', tone: 'warn' },
  'rfq.withdraw': { label: '询价单撤回', tone: 'warn' },
  'rfq.close': { label: '询价单截止', tone: 'warn' },
  'rfq.auto_close': { label: '自动截止', tone: 'danger' },
  'rfq.delete': { label: '询价单删除', tone: 'danger' },
  'rfq.import': { label: '询价单导入', tone: 'warn' },
  'rfq.import_preview': { label: '导入预校验', tone: 'muted' },
  'rfq.export': { label: '询价单导出', tone: 'muted' },
  'quote.save': { label: '报价保存', tone: 'ok' },
  'quote.submit': { label: '报价提交', tone: 'ok' },
  'report.export': { label: '报表导出', tone: 'muted' },
  'user.create': { label: '账号新建', tone: 'warn' },
  'user.update': { label: '账号修改', tone: 'warn' },
  'user.toggle_status': { label: '账号启停用', tone: 'warn' },
  'user.reset_password': { label: '重置密码', tone: 'warn' },
  'supplier.create': { label: '档案新建', tone: 'warn' },
  'supplier.update': { label: '档案修改', tone: 'warn' },
  'supplier.toggle_status': { label: '档案启停用', tone: 'warn' },
  'supplier_account.create': { label: '供货商账号新建', tone: 'warn' },
  'supplier_account.toggle_status': { label: '供货商账号启停用', tone: 'warn' },
  'supplier_account.reset_password': { label: '供货商账号重置密码', tone: 'warn' },
  'supplier_account.import': { label: '批量导入', tone: 'warn' },
  'supplier_account.import_preview': { label: '批量导入预校验', tone: 'muted' },
  'supplier_account.import_error_report': { label: '导入错误报告导出', tone: 'muted' },
  'supplier_account.export': { label: '账号清单导出', tone: 'muted' },
  'unit.create': { label: '单位新增', tone: 'warn' },
  'unit.update': { label: '单位修改', tone: 'warn' },
  'tax.create': { label: '税率新增', tone: 'warn' },
  'tax.update': { label: '税率修改', tone: 'warn' },
  'attachment.upload': { label: '附件上传', tone: 'muted' },
}

const PREFIX_META = {
  auth: { label: '鉴权', tone: 'muted' },
  rfq: { label: '询价单', tone: 'warn' },
  quote: { label: '报价', tone: 'ok' },
  report: { label: '报表', tone: 'muted' },
  user: { label: '账号', tone: 'warn' },
  supplier_account: { label: '供货商账号', tone: 'warn' },
  supplier: { label: '供货商档案', tone: 'warn' },
  unit: { label: '计量单位', tone: 'warn' },
  tax: { label: '税率', tone: 'warn' },
  security: { label: '安全', tone: 'danger' },
}

function actionMeta(action) {
  if (!action) return { label: '—', tone: 'muted' }
  if (ACTION_META[action]) return ACTION_META[action]
  const prefix = String(action).split('.')[0]
  const fallback = PREFIX_META[prefix]
  return fallback ? { label: `${fallback.label}（${action}）`, tone: fallback.tone } : { label: String(action), tone: 'muted' }
}

function roleMeta(role) {
  if (role === 'admin') return { label: '管理员', tone: 'brand' }
  if (role === 'buyer') return { label: '采购员', tone: 'info' }
  if (role === 'supplier') return { label: '供货商', tone: 'muted' }
  return { label: '系统', tone: 'muted' }
}

// ---------------------------------------------------------------------------
// 列表
// ---------------------------------------------------------------------------
const columns = [
  { prop: 'created_at', label: '时间', width: 155, num: true },
  { prop: 'operator_name', label: '操作人', width: 140 },
  { prop: 'role', label: '角色', width: 100 },
  { prop: 'action', label: '动作类型', width: 155 },
  { prop: 'summary', label: '目标对象与摘要' },
  { prop: 'client_ip', label: '客户端 IP', width: 135, num: true, hiddenOn: ['tablet'] },
]

// 手机卡片：标题=操作人，标题右侧=动作徽标，字段保留时间/角色/摘要/IP（避免与标题重复）
const cardFields = [
  { label: '时间', prop: 'created_at', formatter: (row) => formatDateTime(row.created_at) },
  { label: '角色', prop: 'role', formatter: (row) => roleMeta(row.role).label },
  { label: '摘要', prop: 'summary', formatter: (row) => summaryText(row) },
  { label: '客户端 IP', prop: 'client_ip' },
]

function summaryText(row) {
  const text = row.summary || '—'
  if (!row.target_type) return text
  return `${text}（${row.target_type}${row.target_id ? ` #${row.target_id}` : ''}）`
}

function cardTitle(row) {
  return row.operator_name || 'system'
}

const filterCount = computed(() => {
  let count = 0
  if (Array.isArray(state.query.range) && state.query.range.length === 2 && state.query.range[0]) count += 1
  if (state.query.operator.trim()) count += 1
  if (state.query.action) count += 1
  return count
})

function buildParams(page = state.page, pageSize = state.pageSize) {
  const params = { page, page_size: pageSize }
  const range = state.query.range
  if (Array.isArray(range) && range.length === 2 && range[0] && range[1]) {
    params.date_from = range[0]
    params.date_to = range[1]
  }
  if (state.query.operator.trim()) params.operator = state.query.operator.trim()
  if (state.query.action) params.action = state.query.action
  return params
}

async function load() {
  state.loading = true
  try {
    const data = await api.listAuditLogs(buildParams())
    state.rows = data?.items || []
    state.total = Number(data?.meta?.total || 0)
  } catch {
    state.rows = []
    state.total = 0
  } finally {
    state.loading = false
  }
}

function search() {
  state.page = 1
  load()
}

function resetFilter() {
  state.query.range = []
  state.query.operator = ''
  state.query.action = ''
  search()
}

function onPage({ page, pageSize }) {
  state.page = page
  if (pageSize) state.pageSize = pageSize
  load()
}

async function loadActions() {
  try {
    const data = await api.listAuditActions()
    actionOptions.value = Array.isArray(data) ? data : []
  } catch {
    actionOptions.value = []
  }
}

// ---------------------------------------------------------------------------
// 导出（后端无日志导出接口 → 前端 CSV，覆盖当前筛选条件下的全部记录）
// ---------------------------------------------------------------------------
async function exportLogs() {
  state.exporting = true
  try {
    const first = await api.listAuditLogs(buildParams(1, EXPORT_PAGE_SIZE))
    const total = Number(first?.meta?.total || 0)
    const all = [...(first?.items || [])]
    const limit = Math.min(total, MAX_EXPORT_ROWS)
    const pages = Math.ceil(limit / EXPORT_PAGE_SIZE)

    for (let page = 2; page <= pages; page += 1) {
      // 顺序拉取，避免给后端造成并发压力（内网单机部署）
      // eslint-disable-next-line no-await-in-loop
      const data = await api.listAuditLogs(buildParams(page, EXPORT_PAGE_SIZE))
      all.push(...(data?.items || []))
    }

    api.downloadCsv(
      `操作日志_${api.dateStamp()}.csv`,
      [
        { key: 'created_at', label: '时间' },
        { key: 'operator_name', label: '操作人' },
        { key: 'role_text', label: '角色' },
        { key: 'action_text', label: '动作类型' },
        { key: 'target_type', label: '目标类型' },
        { key: 'target_id', label: '目标 ID' },
        { key: 'summary', label: '摘要' },
        { key: 'client_ip', label: '客户端 IP' },
      ],
      all.map((row) => ({
        ...row,
        created_at: formatDateTime(row.created_at),
        role_text: roleMeta(row.role).label,
        action_text: actionMeta(row.action).label,
      })),
    )

    if (total > MAX_EXPORT_ROWS) {
      ElMessage.warning(
        `共 ${total} 条，单次最多导出 ${MAX_EXPORT_ROWS} 条；请收窄时间范围后分批导出`,
      )
    } else {
      ElMessage.success(
        isMobile.value
          ? `已导出 ${all.length} 条日志（CSV），建议在电脑上查看`
          : `已导出 ${all.length} 条日志（CSV，可用 Excel 打开）`,
      )
    }
  } catch {
    /* request.js 已提示错误原因 */
  } finally {
    state.exporting = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadActions()])
})
</script>

<template>
  <div class="sys-page audit-page">
    <header class="sys-head">
      <div>
        <h3 class="sys-head__title">操作日志</h3>
        <p class="sys-head__desc">
          保留 ≥ 12 个月 · 记录登录、发布、截止、报价提交、账号与字典变更 · <b>日志只读，无删除入口</b>
        </p>
      </div>
      <div class="sys-head__actions">
        <el-button :loading="state.exporting" @click="exportLogs">导出日志</el-button>
      </div>
    </header>

    <div class="sys-alert sys-alert--info">
      <span class="sys-alert__icon">i</span>
      <div>
        <b>日志只读：</b>本页没有任何删除或清理入口，管理员也无法删除（FR-LOG-04）。
        系统自动动作（如自动截止）的操作人记为 <span class="sys-num">system</span>。
      </div>
    </div>

    <FilterDrawer
      :active-count="filterCount"
      :loading="state.loading"
      title="筛选日志"
      @search="search"
      @reset="resetFilter"
    >
      <el-form-item label="时间范围">
        <el-date-picker
          v-model="state.query.range"
          class="f-field f-field--wide"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="true"
        />
      </el-form-item>
      <el-form-item label="操作人">
        <el-input
          v-model="state.query.operator"
          class="f-field"
          placeholder="姓名 / 用户名 / 用户 ID"
          clearable
          @keyup.enter="search"
        />
      </el-form-item>
      <el-form-item label="动作类型">
        <el-select
          v-model="state.query.action"
          class="f-field f-field--wide"
          placeholder="全部动作类型"
          clearable
          filterable
        >
          <el-option
            v-for="item in actionOptions"
            :key="item"
            :label="`${actionMeta(item).label}（${item}）`"
            :value="item"
          />
        </el-select>
      </el-form-item>
    </FilterDrawer>

    <DataTable
      :data="state.rows"
      :columns="columns"
      :card-fields="cardFields"
      :card-title="cardTitle"
      :loading="state.loading"
      :pagination="{ page: state.page, pageSize: state.pageSize, total: state.total }"
      empty-text="当前筛选条件下没有日志"
      @page-change="onPage"
    >
      <template #created_at="{ row }">
        <span class="sys-num">{{ formatDateTime(row.created_at) }}</span>
      </template>

      <template #operator_name="{ row }">
        <span class="sys-strong">{{ row.operator_name || 'system' }}</span>
      </template>

      <template #role="{ row }">
        <StatusBadge :label="roleMeta(row.role).label" :tone="roleMeta(row.role).tone" />
      </template>

      <template #action="{ row }">
        <StatusBadge :label="actionMeta(row.action).label" :tone="actionMeta(row.action).tone" />
      </template>

      <template #summary="{ row }">
        <div class="audit-page__summary">
          <span>{{ row.summary || '—' }}</span>
          <span v-if="row.target_type" class="sys-sub">
            目标：{{ row.target_type }}<template v-if="row.target_id"> #{{ row.target_id }}</template>
          </span>
        </div>
      </template>

      <template #client_ip="{ row }">
        <span class="sys-num sys-sub">{{ row.client_ip || '—' }}</span>
      </template>

      <template #card-extra="{ row }">
        <StatusBadge :label="actionMeta(row.action).label" :tone="actionMeta(row.action).tone" />
      </template>
    </DataTable>

    <div class="sys-card__foot audit-page__foot">
      <span>共 {{ state.total }} 条 · 每页 {{ state.pageSize }} 条</span>
      <span class="sys-sub">无删除入口 · 导出 CSV 包含全部字段</span>
    </div>

    <div class="sys-alert sys-alert--info audit-page__hint">
      <span class="sys-alert__icon">i</span>
      <div>
        日志<b>没有删除入口</b>，管理员也无法清理；导出内容包含全部字段。
        系统自动动作（如自动截止）的操作人记为 <span class="sys-num">system</span>，
        越权访问会记录为「越权访问」。
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use './system-shared';
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.f-field {
  width: 100%;
}

@include bp.tablet-up {
  .f-field {
    width: 190px;
  }

  .f-field--wide {
    width: 300px;
  }
}

.audit-page__summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.5;
}

.audit-page__foot {
  margin-top: v.$sp-3;
  justify-content: space-between;
}

.audit-page__hint {
  margin-top: v.$sp-3;
  margin-bottom: 0;
}
</style>
