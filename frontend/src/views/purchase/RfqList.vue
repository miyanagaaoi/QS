<script setup>
/**
 * RfqList.vue — 我方侧「报价单」列表（设计稿 02-1）
 * ---------------------------------------------------------------------------
 * 路由：/purchase/rfq（菜单项，roles: admin/buyer）
 *
 * PRD：FR-RFQ-01~06 / FR-RWD-10 / 10.2
 *  - 桌面：全列 el-table（DataTable 双形态封装）
 *  - 手机：卡片列表，保留 5 个关键字段；高频操作（查看报价/截止）外露，低频收进「更多」
 *  - 操作列随状态变化（草稿→编辑/发布/删除；已发布→查看报价/截止/导出；已截止→查看报价/统计/导出）
 *  - 采购员默认只看自己创建的（后端强制 + 前端显式 only_mine）；管理员可切「全部 / 我创建的」
 *  - 删除草稿二次确认；已发布不可删除（后端 40900 兜底）
 *
 * 字段来源（已 curl 核对 backend/app/schemas.py RfqListItem）：
 *  id / rfq_no / title / project / status / deadline / line_count / supplier_count /
 *  quoted_count / quoted_line_count / created_by_name / created_at
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

import DataTable from '@/components/DataTable.vue'
import FilterDrawer from '@/components/FilterDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import StickyBar from '@/components/StickyBar.vue'
import { closeRfq, deleteRfq, exportRfq, listRfqs, publishRfq } from '@/api/rfq'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatDateTime, formatRemaining, secondsUntil } from '@/composables/useFormat'
import { useUserStore } from '@/stores/user'

import { compactParams, countRfqs, safePush } from './support'

defineOptions({ name: 'RfqList' })

const router = useRouter()
const userStore = useUserStore()
const { isMobile } = useBreakpoint()

const STATUS_FILTERS = [
  { value: '', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'closed', label: '已截止' },
]

const query = reactive({
  status: '',
  keyword: '',
  date_from: '',
  date_to: '',
  // 采购员默认只看自己创建的；管理员默认「全部」
  only_mine: !userStore.isAdmin,
  page: 1,
  page_size: 20,
})

const rows = ref([])
const loading = ref(false)
const meta = reactive({ page: 1, page_size: 20, total: 0 })
const counts = reactive({ draft: 0, published: 0, closed: 0 })
const dateRange = ref([])
const busyId = ref(0)

/** 页头统计（设计稿：「共 12 张单据 · 3 张进行中 · 4 张已截止」） */
const headSummary = computed(
  () => `共 ${meta.total} 张单据 · ${counts.published} 张进行中 · ${counts.closed} 张已截止`,
)

const activeFilterCount = computed(() => {
  let n = 0
  if (query.status) n += 1
  if (query.keyword) n += 1
  if (query.date_from || query.date_to) n += 1
  return n
})

// ---------------------------------------------------------------------------
// 列定义（桌面）
// ---------------------------------------------------------------------------
const columns = [
  { prop: 'rfq_no', label: '询价单号', width: 152, slot: 'rfq_no' },
  { prop: 'title', label: '单据名称 / 项目', minWidth: 200, slot: 'title' },
  { prop: 'deadline', label: '报价截止时间', width: 168, slot: 'deadline' },
  { prop: 'status', label: '状态', width: 96, slot: 'status' },
  { prop: 'line_count', label: '明细行数', width: 92, align: 'right', slot: 'line_count' },
  { prop: 'progress', label: '已报价供货商', width: 176, slot: 'progress' },
  { prop: 'created_by_name', label: '创建人', width: 96, hiddenOn: ['tablet'] },
  { prop: 'created_at', label: '创建时间', width: 140, slot: 'created_at', hiddenOn: ['tablet'] },
]

// ---------------------------------------------------------------------------
// 取数
// ---------------------------------------------------------------------------
async function load() {
  loading.value = true
  try {
    // 可选筛选条件必须剔除空值：`?date_from=&date_to=` 会被后端 date 解析拒绝（40001）
    const params = compactParams({
      page: query.page,
      page_size: query.page_size,
      status: query.status,
      keyword: query.keyword.trim(),
      date_from: query.date_from,
      date_to: query.date_to,
      only_mine: query.only_mine || undefined,
    })
    const data = await listRfqs(params)
    rows.value = Array.isArray(data?.items) ? data.items : []
    const pageMeta = data?.meta || {}
    meta.page = Number(pageMeta.page ?? query.page) || 1
    meta.page_size = Number(pageMeta.page_size ?? query.page_size) || 20
    meta.total = Number(pageMeta.total ?? 0) || 0
  } catch {
    // request.js 已统一 Toast；这里只保证不残留上一次的数据
    rows.value = []
    meta.total = 0
  } finally {
    loading.value = false
  }
}

/** 页头统计：按状态各取一次 total（page_size=1，silent） */
async function loadCounts() {
  const scope = query.only_mine ? { only_mine: true } : {}
  const [published, closed, draft] = await Promise.all([
    countRfqs({ ...scope, status: 'published' }),
    countRfqs({ ...scope, status: 'closed' }),
    countRfqs({ ...scope, status: 'draft' }),
  ])
  counts.published = published
  counts.closed = closed
  counts.draft = draft
}

function search() {
  query.page = 1
  load()
}

function resetFilter() {
  query.status = ''
  query.keyword = ''
  query.date_from = ''
  query.date_to = ''
  dateRange.value = []
  search()
}

function onScopeChange(value) {
  query.only_mine = value === 'mine'
  query.page = 1
  load()
  loadCounts()
}

function onDateRange(value) {
  const [from, to] = Array.isArray(value) ? value : []
  query.date_from = from || ''
  query.date_to = to || ''
}

function onPageChange({ page }) {
  query.page = page
  load()
}

// ---------------------------------------------------------------------------
// 展示辅助
// ---------------------------------------------------------------------------
function remainSeconds(row) {
  if (!row?.deadline) return null
  return secondsUntil(row.deadline)
}

function remainText(row) {
  if (row.status === 'closed') return '已截止'
  const left = remainSeconds(row)
  if (left === null) return '—'
  if (left <= 0) return '已截止'
  return `剩余 ${formatRemaining(left)}`
}

/** 倒计时 <24h 转危险色（FR-RWD-25 / 设计稿） */
function remainTone(row) {
  if (row.status === 'closed') return 'is-plain'
  const left = remainSeconds(row)
  if (left === null || left <= 0) return 'is-plain'
  return left <= 24 * 3600 ? 'is-danger' : 'is-warn'
}

function progressPercent(row) {
  const total = Number(row?.supplier_count || 0)
  if (!total) return 0
  return Math.min(100, Math.round((Number(row?.quoted_count || 0) / total) * 100))
}

/** 进度条颜色：满员=绿、无人报价=品牌色、其余=琥珀（与设计稿一致） */
function progressTone(row) {
  const total = Number(row?.supplier_count || 0)
  const quoted = Number(row?.quoted_count || 0)
  if (total && quoted >= total) return 'is-ok'
  if (quoted > 0) return 'is-warn'
  return ''
}

// ---------------------------------------------------------------------------
// 状态化操作（FR-RFQ-04）
// ---------------------------------------------------------------------------
function goCreate() {
  safePush(router, '/purchase/rfq/new')
}

function goEdit(row) {
  safePush(router, `/purchase/rfq/${row.id}/edit`)
}

function goProgress(row) {
  safePush(router, `/purchase/rfq/${row.id}`)
}

function goReport(row) {
  safePush(router, `/purchase/report?rfq_id=${row.id}&view=comparison`)
}

/**
 * 统一执行 + 错误呈现。
 * 发布校验失败时后端把逐条错误用 \n 拼在 message（如「发布校验未通过：\n第2行 材料名称：必填」），
 * 这里还原成清单展示并阻断（FR-RFQ-10）。
 */
async function run(row, action) {
  busyId.value = row.id
  try {
    await action()
  } catch (error) {
    const lines = String(error?.message || '操作失败')
      .split('\n')
      .map((t) => t.trim())
      .filter(Boolean)
    if (lines.length > 1) {
      await ElMessageBox.alert(lines.slice(1).map((t) => `· ${t}`).join('\n'), lines[0], {
        type: 'warning',
        confirmButtonText: '知道了',
      }).catch(() => {})
    }
    return false
  } finally {
    busyId.value = 0
  }
  return true
}

async function onPublish(row) {
  const confirmed = await ElMessageBox.confirm(
    `发布后将为已勾选的 ${row.supplier_count || 0} 家供货商各生成一份独立报价单，明细行锁定不可修改。\n若校验不通过，系统会逐条列出问题行号并阻断发布。`,
    `发布「${row.title}」？`,
    { type: 'info', confirmButtonText: '发布并通知供货商', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  const ok = await run(row, () => publishRfq(row.id, {}))
  if (ok) {
    ElMessage.success('已发布')
    await Promise.all([load(), loadCounts()])
  }
}

async function onClose(row) {
  const confirmed = await ElMessageBox.confirm(
    '提前截止后供货商将无法再保存或提交报价（已提交的报价保留）。此操作不可撤销。',
    `截止「${row.title}」？`,
    { type: 'warning', confirmButtonText: '确认截止', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  const ok = await run(row, () => closeRfq(row.id, {}))
  if (ok) {
    ElMessage.success('已截止')
    await Promise.all([load(), loadCounts()])
  }
}

/** 删除草稿：二次确认（FR-RFQ-06） */
async function onDelete(row) {
  const confirmed = await ElMessageBox.confirm(
    `将永久删除草稿「${row.title}」（${row.rfq_no}）及其 ${row.line_count} 行明细，删除后不可恢复。\n已发布的单据不可删除，只能截止。`,
    '删除草稿',
    {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    },
  ).catch(() => false)
  if (!confirmed) return
  const ok = await run(row, () => deleteRfq(row.id))
  if (ok) {
    ElMessage.success('已删除')
    await Promise.all([load(), loadCounts()])
  }
}

async function onExport(row) {
  const ok = await run(row, () => exportRfq(row.id))
  if (ok) ElMessage.success('导出已开始')
}

/** 已发布且**未截止** → 可追加受邀供货商（task-11） */
function canAppendSuppliers(row) {
  if (row.status !== 'published') return false
  const left = remainSeconds(row)
  return left !== null && left > 0
}

function goAppend(row) {
  // 追加弹层宿主是「报价进度」页（task-11 指定入口页），带 ?append=1 自动打开
  safePush(router, `/purchase/rfq/${row.id}?append=1`)
}

/**
 * 行操作**单一来源**（FR-RFQ-04：操作列随状态变化）。
 * 桌面表格、手机卡片、手机「更多」下拉都从这里取，避免三处各写一套导致行为漂移。
 * @returns {{key:string,label:string,fullLabel:string,tone:'primary'|'danger',handler:Function}[]}
 */
function actionsFor(row) {
  if (row.status === 'draft') {
    return [
      { key: 'edit', label: '编辑', fullLabel: '编辑草稿', tone: 'primary', handler: () => goEdit(row) },
      { key: 'publish', label: '发布', fullLabel: '发布并通知供货商', tone: 'primary', handler: () => onPublish(row) },
      { key: 'delete', label: '删除', fullLabel: '删除草稿', tone: 'danger', handler: () => onDelete(row) },
    ]
  }
  const list = [
    { key: 'progress', label: '查看报价', fullLabel: '查看报价进度', tone: 'primary', handler: () => goProgress(row) },
  ]
  if (row.status === 'published') {
    list.push({ key: 'close', label: '截止', fullLabel: '提前截止', tone: 'primary', handler: () => onClose(row) })
    // 未截止前可追加供货商：位置放在「截止」之后，
    // 手机端仍外露「查看报价 / 截止」这两个高频动作，「追加供货商」收进「更多」。
    if (canAppendSuppliers(row)) {
      list.push({
        key: 'append',
        label: '追加供货商',
        fullLabel: '追加受邀供货商',
        tone: 'primary',
        handler: () => goAppend(row),
      })
    }
  } else {
    list.push({ key: 'report', label: '统计', fullLabel: '统计报表', tone: 'primary', handler: () => goReport(row) })
  }
  list.push({ key: 'export', label: '导出', fullLabel: '导出询价单 .xlsx', tone: 'primary', handler: () => onExport(row) })
  return list
}

/** 手机端「更多」里的低频动作（命令 → actionsFor 的 key 对应） */
function onMoreCommand(command, row) {
  const action = actionsFor(row).find((item) => item.key === command)
  return action ? action.handler() : undefined
}

onMounted(() => {
  load()
  loadCounts()
})
</script>

<template>
  <div class="rfq-list">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">报价单</h2>
        <p class="page-head__sub">{{ headSummary }}</p>
      </div>
      <div class="page-head__actions">
        <el-radio-group
          v-if="userStore.isAdmin"
          :model-value="query.only_mine ? 'mine' : 'all'"
          size="small"
          @change="onScopeChange"
        >
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="mine">我创建的</el-radio-button>
        </el-radio-group>
        <el-button type="primary" @click="goCreate">+ 新建报价单</el-button>
      </div>
    </header>

    <FilterDrawer
      :active-count="activeFilterCount"
      :loading="loading"
      @search="search"
      @reset="resetFilter"
    >
      <el-form-item label="状态">
        <el-select v-model="query.status" placeholder="全部" clearable style="width: 132px">
          <el-option
            v-for="item in STATUS_FILTERS"
            :key="item.value || 'all'"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="关键字">
        <el-input
          v-model="query.keyword"
          placeholder="单号 / 名称 / 项目"
          clearable
          style="width: 220px"
          @keyup.enter="search"
        />
      </el-form-item>
      <el-form-item label="截止时间">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="~"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 260px"
          @change="onDateRange"
        />
      </el-form-item>
      <el-form-item v-if="!userStore.isAdmin" label="范围">
        <span class="rfq-list__scope-hint">仅我创建的单据</span>
      </el-form-item>
    </FilterDrawer>

    <DataTable
      :data="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :actions-width="248"
      :pagination="{ page: meta.page, pageSize: meta.page_size, total: meta.total }"
      empty-text="还没有符合条件的报价单。点击右上角「新建报价单」录入明细，或调整筛选条件。"
      @page-change="onPageChange"
    >
      <template #rfq_no="{ row }">
        <span class="num rfq-list__no">{{ row.rfq_no }}</span>
      </template>

      <template #title="{ row }">
        <span class="rfq-list__name">{{ row.title }}</span>
        <div class="rfq-list__sub">{{ row.project || '—' }}</div>
      </template>

      <template #deadline="{ row }">
        <template v-if="row.deadline">
          <span class="num">{{ formatDateTime(row.deadline) }}</span>
          <div class="rfq-list__sub" :class="remainTone(row)">{{ remainText(row) }}</div>
        </template>
        <span v-else class="rfq-list__sub">—（草稿未设）</span>
      </template>

      <template #status="{ row }">
        <StatusBadge :status="row.status" />
      </template>

      <template #line_count="{ row }">
        <span class="num">{{ row.line_count }} 行</span>
      </template>

      <!-- 已报价 x/y 家 + 进度条（设计稿 .prog） -->
      <template #progress="{ row }">
        <div v-if="row.status === 'draft'" class="rfq-list__sub">未发布</div>
        <div v-else class="prog">
          <div class="prog__bar" :class="progressTone(row)">
            <i :style="{ width: `${progressPercent(row)}%` }" />
          </div>
          <span class="prog__txt num">{{ row.quoted_count }}/{{ row.supplier_count }} 家</span>
        </div>
      </template>

      <template #created_at="{ row }">
        <span class="num rfq-list__sub">{{ formatDateTime(row.created_at) }}</span>
      </template>

      <!-- 操作列（桌面表格）：全部动作外露 -->
      <template #actions="{ row }">
        <el-button
          v-for="action in actionsFor(row)"
          :key="action.key"
          link
          :type="action.tone"
          :disabled="busyId === row.id"
          @click="action.handler()"
        >
          {{ action.label }}
        </el-button>
      </template>

      <!-- 手机卡片（设计稿 m-card：名称+状态 / 单号·项目·行数 / 剩余·已报价 / 进度） -->
      <template #card="{ row }">
        <div class="m-card" :class="{ 'is-alert': remainTone(row) === 'is-danger' }">
          <div class="m-card__top">
            <h3 class="m-card__ttl">{{ row.title }}</h3>
            <StatusBadge :status="row.status" size="small" />
          </div>
          <div class="m-card__sub">
            <span class="num">{{ row.rfq_no }}</span>
            <span class="m-card__dot">·</span>{{ row.project || '—' }}
            <span class="m-card__dot">·</span>{{ row.line_count }} 行
          </div>
          <div class="m-card__meta">
            <span :class="remainTone(row)">
              {{ row.deadline ? remainText(row) : '未设置截止时间' }}
            </span>
            <span class="m-card__meta-right num">
              {{
                row.status === 'draft'
                  ? '未发布'
                  : `已报价 ${row.quoted_count}/${row.supplier_count} 家`
              }}
            </span>
          </div>
          <div v-if="row.status !== 'draft'" class="prog prog--solo">
            <div class="prog__bar" :class="progressTone(row)">
              <i :style="{ width: `${progressPercent(row)}%` }" />
            </div>
          </div>

          <!-- 卡片操作区：高频动作外露，低频收进「更多」（设计稿 02-1 手机形态）
               注意：DataTable 的默认卡片页脚会被自定义 #card 覆盖，
               所以操作必须在这里显式渲染。 -->
          <footer class="m-card__foot" @click.stop>
            <el-button
              v-for="(action, index) in actionsFor(row).slice(0, 2)"
              :key="action.key"
              link
              :type="action.tone"
              :disabled="busyId === row.id"
              @click="action.handler()"
            >
              {{ action.label }}
            </el-button>
            <el-dropdown
              v-if="actionsFor(row).length > 2"
              trigger="click"
              @command="(cmd) => onMoreCommand(cmd, row)"
            >
              <button type="button" class="rfq-list__more">
                更多
                <span aria-hidden="true">▾</span>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="action in actionsFor(row).slice(2)"
                    :key="action.key"
                    :command="action.key"
                  >
                    {{ action.fullLabel }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </footer>
        </div>
      </template>
    </DataTable>

    <StickyBar v-if="isMobile" class="rfq-list__sticky">
      <span>进行中 <b class="num">{{ counts.published }} 张</b></span>
      <template #actions>
        <el-button type="primary" @click="goCreate">+ 新建报价单</el-button>
      </template>
    </StickyBar>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.rfq-list {
  min-width: 0;
}

// —— 页头 ——
.page-head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
  flex-wrap: wrap;
  margin-bottom: v.$sp-3;
}

.page-head__title {
  font-size: v.$fs-title;
  letter-spacing: -0.015em;
}

.page-head__sub {
  margin-top: 3px;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.page-head__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

.rfq-list__scope-hint {
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

// —— 表格单元格 ——
.rfq-list__no {
  font-size: v.$fs-xs;
  color: v.$ink-700;
}

.rfq-list__name {
  font-weight: 600;
}

.rfq-list__sub {
  font-size: v.$fs-xs;
  color: v.$ink-400;

  &.is-warn {
    color: v.$warn;
    font-weight: 600;
  }

  &.is-danger {
    color: v.$danger;
    font-weight: 700;
  }
}

// —— 进度条（设计稿 .prog）——
.prog {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  min-width: 118px;
}

.prog--solo .prog__bar {
  flex: 1;
}

.prog__bar {
  flex: 1;
  min-width: 52px;
  height: 5px;
  border-radius: 100px;
  background: v.$line;
  overflow: hidden;

  i {
    display: block;
    height: 100%;
    border-radius: 100px;
    background: v.$brand-600;
  }

  &.is-warn i {
    background: v.$warn;
  }

  &.is-ok i {
    background: v.$ok;
  }
}

.prog__txt {
  flex: none;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

// —— 手机端 ——
.rfq-list__more {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-height: v.$touch-target;
  padding: 0 v.$sp-2;
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$ink-400;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.m-card {
  padding: v.$sp-3;

  &.is-alert {
    border-color: v.$danger-line;
  }
}

.m-card__top {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-2;
}

.m-card__ttl {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-body;
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.m-card__sub {
  margin-top: 5px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.m-card__dot {
  margin: 0 4px;
  color: v.$ink-300;
}

.m-card__meta {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-top: 9px;
  font-size: v.$fs-xs;
  color: v.$ink-400;

  .is-warn {
    color: v.$warn;
    font-weight: 600;
  }

  .is-danger {
    color: v.$danger;
    font-weight: 700;
  }
}

.m-card__meta-right {
  margin-left: auto;
  color: v.$ink-500;
}

.m-card .prog--solo {
  margin-top: v.$sp-2;
}

// 手机卡片操作区（FR-RWD-06：热区 ≥44px）
.m-card__foot {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  margin-top: v.$sp-2;
  padding-top: v.$sp-2;
  border-top: 1px dashed v.$line;

  :deep(.el-button) {
    min-width: v.$touch-target;
    min-height: v.$touch-target;
    margin-left: 0;
    padding: 0 v.$sp-1;
  }
}

@include bp.mobile {
  .rfq-list {
    // 为吸底操作栏预留空间
    padding-bottom: calc(v.$bottom-bar-h + 24px);
  }

  .page-head__actions {
    width: 100%;

    :deep(.el-button) {
      flex: 1;
      min-height: v.$touch-target;
    }
  }
}
</style>
