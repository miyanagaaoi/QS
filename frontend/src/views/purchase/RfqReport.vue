<script setup>
/**
 * RfqReport.vue — 报价单统计报表（设计稿 02-4）
 * ---------------------------------------------------------------------------
 * 路由：/purchase/report（菜单项）、/purchase/rfq/:id/report
 *      query：rfq_id（预选单据）、view=comparison|summary
 *
 * PRD：FR-RPT-01~04 / FR-RWD-13 / 10.2
 *  视图 A 比价明细（P0）
 *    - 交叉表：行=物料需求，列=各供货商（列头显示"最低价 ×N"的胜出次数，即最低价方）
 *    - 最低价单元格：琥珀底 #FFFBEB + 左侧强调边 #F5D77A + 字色 #8A5A00（设计系统唯一允许的饱和暖色）
 *    - 附表列：最低价 / 最低价方 / 最高价 / 均价 / 价差率 / 报价家数（已报价÷受邀）
 *    - 支持按最低价升/降序排序；手机端横向滚动 + 首列冻结 + 表头固定
 *  视图 B 汇总统计（P0）
 *    - 指标卡：询价单数 / 明细行数 / 受邀家次 / 已报价家次 / 响应率 / 报价总金额
 *    - 按供货商汇总 + 按项目汇总；手机端指标卡两列、表格转卡片
 *  筛选：询价单 / 时间范围 / 项目 / 供货商 / 只显示未报价；两个 .xlsx 导出
 *
 * 字段来源（已 curl 核对 backend/app/schemas.py）：
 *  ComparisonResult：rfq_id/rfq_no/title/project/status/
 *    suppliers[{supplier_id,supplier_name,status}]/
 *    rows[{line_uid,seq,material_name,spec,unit,quantity,project,
 *          prices{"<supplier_id>":"含税单价字符串"},
 *          best_price,best_supplier_id,best_supplier_name,max_price,avg_price,
 *          diff_rate,quoted_count,required_count}]/
 *    total_best_amount,total_max_amount,saved_amount,saved_rate
 *  SummaryResult：date_from/date_to/rfq_count/line_count/invited_assignments/
 *    quoted_assignments/response_rate/best_amount/
 *    by_supplier[{supplier_id,supplier_name,invited_count,quoted_count,response_rate,amount,avg_lead_time,avg_moq}]/
 *    by_project[{project,rfq_count,line_count,coverage_rate,best_amount}]
 *
 * 比率字段（diff_rate / saved_rate / response_rate / coverage_rate）实测有**两种形态**：
 * 旧版返回小数 "0.1538"，新版返回已格式化字符串 "27.3%" / "0.0%"。
 * 因此一律经 support.js 的 rateText()/parseRate() 处理，绝不直接用 formatPercent（会 ×100）。
 *
 * 说明：prices 的键是 supplier_id 的**字符串**（JSON 对象键），比较时统一 String() 归一。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import 'element-plus/es/components/message/style/css'

import FilterDrawer from '@/components/FilterDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { listRfqs } from '@/api/rfq'
import { exportSummary, getRfqComparison, getSummary } from '@/api/report'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useUserStore } from '@/stores/user'
import {
  formatMoney,
  formatQty,
  formatDate,
} from '@/composables/useFormat'

import { compactParams, exportComparison, listSupplierOptions, parseRate, rateText } from './support'

defineOptions({ name: 'RfqReport' })

const route = useRoute()
const { isMobile } = useBreakpoint()
const userStore = useUserStore()

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const view = ref(route.query.view === 'summary' ? 'summary' : 'comparison')
const loading = ref(false)
const exporting = ref(false)

/** 视图 A */
const rfqOptions = ref([])
const comparison = ref(null)
const compare = reactive({
  rfq_id: Number(route.query.rfq_id) || null,
  project: '',
  supplier_id: null,
  only_unquoted: false,
  sort: '',
})

/** 视图 B */
const supplierOptions = ref([])
const summary = ref(null)
const sumFilter = reactive({
  date_from: '',
  date_to: '',
  project: '',
  supplier_ids: [],
  only_unquoted: false,
  rfq_id: null,
})

const activeFilterCount = computed(() => {
  if (view.value === 'comparison') {
    let n = 0
    if (compare.rfq_id) n += 1
    if (compare.project) n += 1
    if (compare.supplier_id) n += 1
    if (compare.only_unquoted) n += 1
    return n
  }
  let n = 0
  if (sumFilter.date_from || sumFilter.date_to) n += 1
  if (sumFilter.project) n += 1
  if (sumFilter.supplier_ids.length) n += 1
  if (sumFilter.rfq_id) n += 1
  if (sumFilter.only_unquoted) n += 1
  return n
})

// ---------------------------------------------------------------------------
// 视图 A 派生
// ---------------------------------------------------------------------------
const visibleSuppliers = computed(() => {
  const list = comparison.value?.suppliers || []
  if (!compare.supplier_id) return list
  return list.filter((s) => Number(s.supplier_id) === Number(compare.supplier_id))
})

/** 各供货商拿下「该行最低价」的次数（列头展示最低价方，让采购员一眼看出谁最能打） */
const bestWins = computed(() => {
  const map = {}
  ;(comparison.value?.rows || []).forEach((row) => {
    if (row.best_supplier_id === null || row.best_supplier_id === undefined) return
    const key = String(row.best_supplier_id)
    map[key] = (map[key] || 0) + 1
  })
  return map
})

const displayRows = computed(() => {
  const rows = [...(comparison.value?.rows || [])]
  const keyword = compare.project.trim()
  const filtered = keyword
    ? rows.filter(
        (row) =>
          String(row.project || '').includes(keyword) ||
          String(row.material_name || '').includes(keyword),
      )
    : rows

  if (!compare.sort) return filtered
  const sign = compare.sort === 'asc' ? 1 : -1
  return filtered.sort((a, b) => {
    const av = a.best_price === null || a.best_price === undefined ? Infinity : Number(a.best_price)
    const bv = b.best_price === null || b.best_price === undefined ? Infinity : Number(b.best_price)
    if (av === bv) return 0
    return av > bv ? sign : -sign
  })
})

/** 有明细但一条报价都没有 → 明确空状态文案 */
const noQuotes = computed(() => {
  const rows = comparison.value?.rows || []
  return rows.length > 0 && rows.every((row) => Number(row.quoted_count || 0) === 0)
})

const quoteStats = computed(() => {
  const result = comparison.value
  if (!result) return ''
  const quoted = (result.suppliers || []).filter((s) => s.status === 'quoted').length
  return `${result.rows?.length ?? 0} 行 · ${result.suppliers?.length ?? 0} 家供货商 · 已报价 ${quoted}/${result.suppliers?.length ?? 0}`
})

function cellPrice(row, supplierId) {
  const raw = row?.prices?.[String(supplierId)]
  if (raw === null || raw === undefined || raw === '') return null
  return raw
}

function isBestCell(row, supplierId) {
  const raw = cellPrice(row, supplierId)
  if (raw === null) return false
  if (row.best_price === null || row.best_price === undefined) return false
  return Number(raw) === Number(row.best_price)
}

function money(value) {
  return formatQty(value, { digits: 2, minDigits: 2 })
}

/**
 * 响应率 / 覆盖率 → 徽标语义色。
 * 用 parseRate 兼容后端两种比率形态（"33.3%" 与 "0.333"）。
 */
function rateTone(value) {
  const rate = parseRate(value)
  if (rate === null) return 'unpriced'
  if (rate >= 0.9) return 'quoted'
  if (rate > 0) return 'partial'
  return 'unpriced'
}

/** 按最低价排序（升/降/取消） */
function toggleSort() {
  compare.sort = compare.sort === 'asc' ? 'desc' : compare.sort === 'desc' ? '' : 'asc'
}

const sortLabel = computed(() => {
  if (compare.sort === 'asc') return '最低价 ↑'
  if (compare.sort === 'desc') return '最低价 ↓'
  return '按最低价排序'
})

// ---------------------------------------------------------------------------
// 视图 B 派生
// ---------------------------------------------------------------------------
const summaryHead = computed(() => {
  const s = summary.value
  if (!s) return ''
  const range = s.date_from || s.date_to ? `${s.date_from || '不限'} ~ ${s.date_to || '今天'}` : '全部时间'
  return `${range} · 覆盖 ${s.rfq_count} 张询价单`
})

const kpis = computed(() => {
  const s = summary.value
  if (!s) return []
  return [
    { key: 'rfq_count', label: '询价单数', value: String(s.rfq_count), unit: '张', desc: `覆盖 ${s.by_project?.length ?? 0} 个项目` },
    { key: 'line_count', label: '明细行数', value: String(s.line_count), unit: '行', desc: '全部单据明细合计' },
    { key: 'invited', label: '受邀家次', value: String(s.invited_assignments), unit: '家次', desc: '单据 × 供货商' },
    { key: 'quoted', label: '已报价家次', value: String(s.quoted_assignments), unit: '家次', desc: '按「提交报价」计' },
    { key: 'rate', label: '供货商响应率', value: rateText(s.response_rate), unit: '', desc: `已报价 ${s.quoted_assignments} / 受邀 ${s.invited_assignments} 家次`, tone: 'ok' },
    { key: 'amount', label: '报价总金额', value: formatMoney(s.best_amount), unit: '', desc: '按各行最低含税单价 × 采购数量' },
  ]
})

// ---------------------------------------------------------------------------
// 取数
// ---------------------------------------------------------------------------
async function loadRfqOptions() {
  try {
    const data = await listRfqs({ page: 1, page_size: 200 })
    rfqOptions.value = (data?.items || []).map((item) => ({
      id: item.id,
      label: `${item.rfq_no} · ${item.title}`,
      status: item.status,
    }))
    // 未指定单据时默认选最新一张，让视图 A 一进来就有数据
    if (!compare.rfq_id && rfqOptions.value.length) {
      compare.rfq_id = rfqOptions.value[0].id
    }
  } catch {
    rfqOptions.value = []
  }
}

async function loadComparison() {
  if (!compare.rfq_id) {
    comparison.value = null
    return
  }
  loading.value = true
  try {
    comparison.value = await getRfqComparison({
      rfq_id: compare.rfq_id,
      only_unquoted: compare.only_unquoted,
    })
  } catch {
    comparison.value = null
  } finally {
    loading.value = false
  }
}

/** 汇总查询参数：可选筛选一律剔除空值（空串会被后端 date 解析拒绝，见 support.compactParams） */
function summaryParams() {
  return compactParams({
    date_from: sumFilter.date_from,
    date_to: sumFilter.date_to,
    project: sumFilter.project.trim(),
    supplier_ids: sumFilter.supplier_ids.length ? sumFilter.supplier_ids.join(',') : '',
    rfq_id: sumFilter.rfq_id,
    only_unquoted: sumFilter.only_unquoted || undefined,
  })
}

async function loadSummary() {
  loading.value = true
  try {
    summary.value = await getSummary(summaryParams())
  } catch {
    summary.value = null
  } finally {
    loading.value = false
  }
}

function search() {
  if (view.value === 'comparison') loadComparison()
  else loadSummary()
}

function switchView(next) {
  view.value = next
  if (next === 'comparison') {
    if (!comparison.value) loadComparison()
  } else if (!summary.value) {
    loadSummary()
  }
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------
async function onExport() {
  exporting.value = true
  try {
    if (view.value === 'comparison') {
      if (!compare.rfq_id) {
        ElMessage.warning('请先选择一张询价单')
        return
      }
      await exportComparison(
        compactParams({ rfq_id: compare.rfq_id, only_unquoted: compare.only_unquoted || undefined }),
        '比价明细.xlsx',
      )
    } else {
      await exportSummary(summaryParams())
    }
    ElMessage.success('导出已开始')
  } catch {
    /* request.js 已统一 Toast（后端以 JSON 信封返回错误时会解析并提示） */
  } finally {
    exporting.value = false
  }
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------
function defaultRange() {
  const today = new Date()
  const from = new Date(today.getTime() - 29 * 86400000)
  return { from: formatDate(from), to: formatDate(today) }
}

onMounted(async () => {
  const range = defaultRange()
  sumFilter.date_from = range.from
  sumFilter.date_to = range.to
  sumFilter.rfq_id = Number(route.query.rfq_id) || null

  // 必须先等单据列表加载完：loadRfqOptions 里会给 compare.rfq_id 兜底默认值
  // （未指定单据时选最新一张）。此前这里没有 await，导致查询先于默认选中执行，
  // 出现"下拉已显示某单据、表格却是空的（没有符合筛选条件的明细行）"的矛盾状态。
  await loadRfqOptions()
  listSupplierOptions()
    .then((list) => {
      supplierOptions.value = Array.isArray(list) ? list : []
    })
    .catch(() => {
      supplierOptions.value = []
    })

  if (view.value === 'comparison') await loadComparison()
  else await loadSummary()

  // 路由带 rfq_id 时，视图 A 用它（loadRfqOptions 不会覆盖已有值）
  if (route.query.rfq_id) {
    compare.rfq_id = Number(route.query.rfq_id)
    view.value = 'comparison'
    await loadComparison()
  }
})
</script>

<template>
  <div class="rfq-report">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">报价单统计报表</h2>
        <p class="page-head__sub">
          <template v-if="view === 'comparison'">
            {{ comparison ? `${comparison.title} · ${comparison.rfq_no}` : '数据实时计算 · 供货商保存报价后刷新即可见' }}
          </template>
          <template v-else>{{ summaryHead || '数据实时计算' }}</template>
          <!-- 采购员的数据范围由服务端强制收窄（只能统计自己创建的询价单），
               这里明确告知，避免误以为报表漏数据 -->
          <span v-if="!userStore.isAdmin" class="page-head__scope">统计范围：仅我创建的单据</span>
        </p>
      </div>
      <div class="page-head__actions">
        <el-radio-group
          :model-value="view"
          size="small"
          @change="switchView"
        >
          <el-radio-button value="comparison">比价明细</el-radio-button>
          <el-radio-button value="summary">汇总统计</el-radio-button>
        </el-radio-group>
        <el-button :loading="exporting" @click="onExport">
          {{ view === 'comparison' ? '导出比价明细' : '导出汇总 .xlsx' }}
        </el-button>
      </div>
    </header>

    <!-- ================= 筛选 ================= -->
    <FilterDrawer
      :active-count="activeFilterCount"
      :loading="loading"
      @search="search"
      @reset="search"
    >
      <template v-if="view === 'comparison'">
        <el-form-item label="报价单">
          <el-select
            v-model="compare.rfq_id"
            filterable
            placeholder="选择询价单"
            style="min-width: 260px"
            @change="loadComparison"
          >
            <el-option
              v-for="item in rfqOptions"
              :key="item.id"
              :label="item.label"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="项目 / 物料">
          <el-input v-model="compare.project" placeholder="全部" clearable style="width: 150px" />
        </el-form-item>
        <el-form-item label="供货商">
          <el-select
            v-model="compare.supplier_id"
            clearable
            placeholder="全部"
            style="min-width: 150px"
          >
            <el-option
              v-for="item in comparison?.suppliers || []"
              :key="item.supplier_id"
              :label="item.supplier_name"
              :value="item.supplier_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label=" ">
          <el-checkbox v-model="compare.only_unquoted" @change="loadComparison">
            只显示未报价
          </el-checkbox>
        </el-form-item>
      </template>

      <template v-else>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="sumFilter.date_from"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="开始"
            style="width: 150px"
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-date-picker
            v-model="sumFilter.date_to"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="结束"
            style="width: 150px"
          />
        </el-form-item>
        <el-form-item label="项目">
          <el-input v-model="sumFilter.project" placeholder="全部" clearable style="width: 140px" />
        </el-form-item>
        <el-form-item label="供货商">
          <el-select
            v-model="sumFilter.supplier_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部"
            style="min-width: 170px"
          >
            <el-option
              v-for="item in supplierOptions"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label=" ">
          <el-checkbox v-model="sumFilter.only_unquoted">只显示未报价</el-checkbox>
        </el-form-item>
      </template>
    </FilterDrawer>

    <!-- ================= 视图 A：比价明细 ================= -->
    <template v-if="view === 'comparison'">
      <div v-if="!compare.rfq_id" class="empty-card">
        <el-empty description="请先在筛选区选择一张询价单，即可查看各供货商的逐行比价" :image-size="80" />
      </div>

      <template v-else>
        <section class="card">
          <div class="card__head">
            <b>比价明细</b>
            <span class="card__sub">{{ quoteStats }}</span>
            <div class="card__tools">
              <button type="button" class="linkbtn" @click="toggleSort">{{ sortLabel }}</button>
              <span class="legend">琥珀底 = 该行最低价</span>
            </div>
          </div>

          <div v-if="noQuotes" class="empty-inline">
            <b>该询价单暂无供货商报价。</b>
            系统不发送通知，请到「报价进度」页按未报价名单线下催办；供货商保存报价后刷新本页即可见。
          </div>

          <div v-else class="matrix-wrap xj-hscroll">
            <table class="matrix">
              <thead>
                <tr>
                  <th class="sticky-col">物料 / 需求</th>
                  <th
                    v-for="supplier in visibleSuppliers"
                    :key="supplier.supplier_id"
                    class="is-num"
                  >
                    {{ supplier.supplier_name }}
                    <span class="v">含税单价</span>
                    <span v-if="bestWins[String(supplier.supplier_id)]" class="win num">
                      最低 ×{{ bestWins[String(supplier.supplier_id)] }}
                    </span>
                  </th>
                  <th class="is-num col-sum">最低价<span class="v">含税</span></th>
                  <th class="col-best">最低价方</th>
                  <th class="is-num">最高价</th>
                  <th class="is-num">均价</th>
                  <th class="is-num">价差率</th>
                  <th class="is-num">报价家数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in displayRows" :key="row.line_uid">
                  <td class="sticky-col mat">
                    <b>{{ row.material_name }}</b>
                    <span>
                      {{ row.spec || '—' }} · {{ row.unit }} · {{ formatQty(row.quantity) }}
                    </span>
                  </td>
                  <td
                    v-for="supplier in visibleSuppliers"
                    :key="supplier.supplier_id"
                    class="price"
                    :class="{
                      best: isBestCell(row, supplier.supplier_id),
                      none: cellPrice(row, supplier.supplier_id) === null,
                    }"
                  >
                    <template v-if="cellPrice(row, supplier.supplier_id) !== null">
                      {{ money(cellPrice(row, supplier.supplier_id)) }}
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td class="price col-sum" :class="{ 'is-best': row.best_price != null }">
                    {{ row.best_price != null ? money(row.best_price) : '—' }}
                  </td>
                  <td class="col-best">
                    <template v-if="row.best_supplier_name">
                      <span class="badge-best">{{ row.best_supplier_name }}</span>
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td class="price">{{ row.max_price != null ? money(row.max_price) : '—' }}</td>
                  <td class="price muted">
                    {{ row.avg_price != null ? money(row.avg_price) : '—' }}
                  </td>
                  <td class="price">
                    {{ rateText(row.diff_rate) }}
                  </td>
                  <td class="price">
                    <span class="num">{{ row.quoted_count }}/{{ row.required_count }}</span>
                  </td>
                </tr>
                <tr v-if="!displayRows.length">
                  <td :colspan="visibleSuppliers.length + 7" class="matrix-empty">
                    没有符合当前筛选条件的明细行，请调整「项目 / 物料」关键字
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="comparison" class="card__foot">
            <span>
              报价总金额（按最低价计）
              <b class="num">{{ formatMoney(comparison.total_best_amount) }}</b>
              <template v-if="comparison.saved_amount">
                · 较最高价方案节省
                <b class="num is-ok">{{ formatMoney(comparison.saved_amount) }}</b>
                （{{ rateText(comparison.saved_rate) }}）
              </template>
            </span>
            <span class="card__foot-right">
              共 {{ displayRows.length }} 行
              <template v-if="compare.sort">· 已按最低价{{ compare.sort === 'asc' ? '升序' : '降序' }}</template>
            </span>
          </div>
        </section>

        <!-- 手机端：附表说明（交叉表已含全部统计列，这里做口径说明） -->
        <p v-if="isMobile && !noQuotes" class="mobile-note">
          左右滑动查看各供货商报价；「物料 / 需求」列已冻结。琥珀底为该行最低价。
        </p>
      </template>
    </template>

    <!-- ================= 视图 B：汇总统计 ================= -->
    <template v-else>
      <!-- 手机端：先给结论（设计稿深色卡） -->
      <section v-if="isMobile" class="hero">
        <div class="hero__label">报价总金额（按各行最低价）</div>
        <div class="hero__value num">{{ formatMoney(summary?.best_amount) }}</div>
        <div class="hero__sub">{{ summaryHead || '—' }}</div>
      </section>

      <section class="kpis">
        <article v-for="kpi in kpis" :key="kpi.key" class="kpi">
          <div class="kpi__k">{{ kpi.label }}</div>
          <div class="kpi__v num" :class="{ 'is-ok': kpi.tone === 'ok' }">
            {{ kpi.value }}<small v-if="kpi.unit">{{ kpi.unit }}</small>
          </div>
          <div class="kpi__d">{{ kpi.desc }}</div>
        </article>
        <article v-if="!kpis.length" class="kpi kpi--skeleton">
          <div class="kpi__k">加载中…</div>
        </article>
      </section>

      <div class="two">
        <!-- 按供货商汇总 -->
        <section class="card">
          <div class="card__head">
            <b>按供货商汇总</b>
            <span class="card__sub">{{ summary?.by_supplier?.length ?? 0 }} 家</span>
          </div>
          <div v-if="isMobile" class="cards">
            <article
              v-for="row in summary?.by_supplier || []"
              :key="row.supplier_id"
              class="m-row"
            >
              <div class="m-row__top">
                <b>{{ row.supplier_name }}</b>
                <StatusBadge
                  :status="rateTone(row.response_rate)"
                  :label="rateText(row.response_rate)"
                  size="small"
                />
              </div>
              <dl class="dl">
                <dt>受邀 / 已报价</dt>
                <dd class="num">{{ row.invited_count }} / {{ row.quoted_count }}</dd>
                <dt>报价金额</dt>
                <dd class="num">{{ formatMoney(row.amount) }}</dd>
                <dt>平均交期</dt>
                <dd class="num">{{ row.avg_lead_time ? `${formatQty(row.avg_lead_time, { digits: 1, minDigits: 1 })} 天` : '—' }}</dd>
              </dl>
            </article>
            <el-empty
              v-if="!summary?.by_supplier?.length"
              description="所选时间范围内暂无供货商报价数据"
              :image-size="72"
            />
          </div>
          <div v-else class="table-wrap">
            <table class="tbl">
              <thead>
                <tr>
                  <th>供货商</th>
                  <th class="r">受邀</th>
                  <th class="r">已报价</th>
                  <th class="r">响应率</th>
                  <th class="r">报价金额</th>
                  <th class="r">平均交期</th>
                  <th class="r">平均 MOQ</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in summary?.by_supplier || []" :key="row.supplier_id">
                  <td class="name">{{ row.supplier_name }}</td>
                  <td class="r num">{{ row.invited_count }}</td>
                  <td class="r num">{{ row.quoted_count }}</td>
                  <td class="r">
                    <StatusBadge
                      :status="rateTone(row.response_rate)"
                      :label="rateText(row.response_rate)"
                      size="small"
                    />
                  </td>
                  <td class="r num">{{ formatMoney(row.amount) }}</td>
                  <td class="r num">
                    {{ row.avg_lead_time ? `${formatQty(row.avg_lead_time, { digits: 1, minDigits: 1 })} 天` : '—' }}
                  </td>
                  <td class="r num">{{ row.avg_moq != null ? formatQty(row.avg_moq, { digits: 2 }) : '—' }}</td>
                </tr>
                <tr v-if="!summary?.by_supplier?.length">
                  <td colspan="7" class="tbl-empty">所选时间范围内暂无供货商报价数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 按项目汇总 -->
        <section class="card">
          <div class="card__head">
            <b>按项目汇总</b>
            <span class="card__sub">{{ summary?.by_project?.length ?? 0 }} 个项目</span>
          </div>
          <div v-if="isMobile" class="cards">
            <article v-for="row in summary?.by_project || []" :key="row.project" class="m-row">
              <div class="m-row__top">
                <b>{{ row.project }}</b>
                <StatusBadge
                  :status="rateTone(row.coverage_rate)"
                  :label="`覆盖率 ${rateText(row.coverage_rate)}`"
                  size="small"
                />
              </div>
              <dl class="dl">
                <dt>询价单 / 明细行</dt>
                <dd class="num">{{ row.rfq_count }} / {{ row.line_count }}</dd>
                <dt>最低价合计</dt>
                <dd class="num">{{ formatMoney(row.best_amount) }}</dd>
              </dl>
            </article>
            <el-empty
              v-if="!summary?.by_project?.length"
              description="所选时间范围内暂无项目数据"
              :image-size="72"
            />
          </div>
          <div v-else class="table-wrap">
            <table class="tbl">
              <thead>
                <tr>
                  <th>项目</th>
                  <th class="r">询价单</th>
                  <th class="r">明细行</th>
                  <th class="r">覆盖率</th>
                  <th class="r">最低价合计</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in summary?.by_project || []" :key="row.project">
                  <td class="name">{{ row.project }}</td>
                  <td class="r num">{{ row.rfq_count }}</td>
                  <td class="r num">{{ row.line_count }}</td>
                  <td class="r">
                    <StatusBadge
                      :status="rateTone(row.coverage_rate)"
                      :label="rateText(row.coverage_rate)"
                      size="small"
                    />
                  </td>
                  <td class="r num">{{ formatMoney(row.best_amount) }}</td>
                </tr>
                <tr v-if="!summary?.by_project?.length">
                  <td colspan="5" class="tbl-empty">所选时间范围内暂无项目数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div class="alert alert--info">
        <span class="alert__i">i</span>
        <div>
          <b>数据口径说明：</b>响应率 = 已报价家次 ÷ 受邀家次；报价总金额按每行
          <b>最低含税单价 × 采购数量</b>累计；平均交期仅统计已填「交货周期」的报价行。
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.rfq-report {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
}

// —— 页头 ——
.page-head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
  flex-wrap: wrap;
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

/* 非管理员的数据范围提示：与副标题同行，弱化处理但保证可读 */
.page-head__scope {
  display: inline-block;
  margin-left: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  background: v.$info-bg;
  color: v.$info;
  font-size: v.$fs-xs;
  white-space: nowrap;
}

.page-head__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

// —— 卡片 ——
.card {
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  min-width: 0;
}

.card__head {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
  padding: v.$sp-3 v.$sp-4;
  border-bottom: 1px solid v.$line;

  b {
    font-size: v.$fs-lg;
  }
}

.card__sub {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.card__tools {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-3;
}

.linkbtn {
  min-height: 28px;
  padding: 0 v.$sp-2;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$brand-700;
  background: transparent;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-sm;
  cursor: pointer;

  &:hover {
    border-color: v.$brand-600;
  }
}

.legend {
  padding: 2px v.$sp-2;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$best-ink;
  background: v.$best-bg;
  border: 1px solid v.$best-line;
  border-radius: v.$r-sm;
}

.card__foot {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: 10px v.$sp-4;
  border-top: 1px solid v.$line;
  font-size: v.$fs-sm;
  color: v.$ink-500;
  flex-wrap: wrap;

  .is-ok {
    color: v.$ok;
  }
}

.card__foot-right {
  margin-left: auto;
  color: v.$ink-400;
}

// —— 交叉表（设计稿 .matrix）——
.matrix-wrap {
  // 手机端唯一允许的横向滚动形态（.xj-hscroll 来自全局样式）
  width: 100%;
}

.matrix {
  width: 100%;
  min-width: 880px;
  border-collapse: separate;
  border-spacing: 0;
  font-size: v.$fs-sm;

  th,
  td {
    padding: 9px v.$sp-3;
    white-space: nowrap;
    border-bottom: 1px solid v.$line-soft;
  }

  thead th {
    position: sticky;
    top: 0;
    z-index: 2;
    font-size: v.$fs-xs;
    font-weight: 600;
    color: v.$ink-500;
    text-align: left;
    background: v.$surface-sunken;
    border-bottom: 1px solid v.$line;
  }

  thead th .v {
    display: block;
    font-size: 10.5px;
    font-weight: 500;
    color: v.$ink-300;
  }

  thead th .win {
    display: inline-block;
    margin-top: 2px;
    padding: 0 5px;
    font-size: 10px;
    font-weight: 700;
    color: v.$best-ink;
    background: v.$best-bg;
    border: 1px solid v.$best-line;
    border-radius: v.$r-sm;
  }

  // 首列冻结（PRD 10.2：手机端保留横向滚动并冻结"物料"首列）
  .sticky-col {
    position: sticky;
    left: 0;
    z-index: 1;
    background: v.$surface;
    border-right: 1px solid v.$line;
  }

  thead .sticky-col {
    z-index: 3;
    background: v.$surface-sunken;
  }

  tbody tr:hover td {
    background: v.$brand-50;
  }

  tbody tr:hover .sticky-col {
    background: v.$brand-50;
  }

  .mat {
    min-width: 210px;
    white-space: normal;

    b {
      display: block;
      font-weight: 600;
    }

    span {
      font-size: v.$fs-xs;
      color: v.$ink-400;
    }
  }

  .is-num {
    text-align: right;
  }

  .price {
    font-family: v.$font-num;
    font-variant-numeric: tabular-nums;
    text-align: right;
    letter-spacing: -0.01em;
  }

  // 最低价：琥珀底 + 左侧强调边（设计系统唯一允许的饱和暖色）
  .best {
    color: v.$best-ink;
    font-weight: 700;
    background: v.$best-bg !important;
    box-shadow: inset 3px 0 0 v.$best-line;
  }

  .none {
    color: v.$ink-300;
  }

  .muted {
    color: v.$ink-500;
  }

  .col-sum {
    background: v.$surface-sunken;
  }

  .col-sum.is-best {
    color: v.$best-ink;
    font-weight: 700;
    background: v.$best-bg !important;
  }

  .col-best {
    white-space: nowrap;
  }

  .badge-best {
    display: inline-block;
    padding: 1px 7px;
    font-size: v.$fs-xs;
    font-weight: 600;
    color: v.$best-ink;
    background: v.$best-bg;
    border: 1px solid v.$best-line;
    border-radius: 100px;
  }

  .matrix-empty {
    padding: v.$sp-6;
    color: v.$ink-400;
    text-align: center;
    white-space: normal;
  }
}

.mobile-note {
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

// —— 空状态 ——
.empty-card,
.empty-inline {
  padding: v.$sp-5 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
}

.empty-inline {
  font-size: v.$fs-sm;
  color: v.$ink-500;

  b {
    color: v.$warn;
  }
}

// —— 指标卡 ——
.hero {
  padding: v.$sp-4;
  color: #fff;
  background: v.$brand-800;
  border-radius: v.$r-lg;
}

.hero__label {
  font-size: v.$fs-xs;
  opacity: 0.8;
}

.hero__value {
  margin-top: 4px;
  font-size: 1.625rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.hero__sub {
  margin-top: 2px;
  font-size: v.$fs-xs;
  opacity: 0.75;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: v.$sp-3;
}

.kpi {
  padding: v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  min-width: 0;
}

.kpi__k {
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-500;
}

.kpi__v {
  margin: 6px 0 3px;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;

  small {
    margin-left: 2px;
    font-size: v.$fs-sm;
    font-weight: 600;
    color: v.$ink-400;
  }

  &.is-ok {
    color: v.$ok;
  }
}

.kpi__d {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: v.$sp-3;
}

// —— 汇总表 ——
.table-wrap {
  overflow-x: auto;
}

.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: v.$fs-sm;

  th {
    padding: 9px v.$sp-3;
    font-size: v.$fs-xs;
    font-weight: 600;
    color: v.$ink-500;
    text-align: left;
    white-space: nowrap;
    background: v.$surface-sunken;
    border-bottom: 1px solid v.$line;
  }

  td {
    padding: 10px v.$sp-3;
    border-bottom: 1px solid v.$line-soft;
  }

  tbody tr:last-child td {
    border-bottom: 0;
  }

  .r {
    text-align: right;
  }

  .name {
    font-weight: 600;
  }

  .tbl-empty {
    padding: v.$sp-6;
    color: v.$ink-400;
    text-align: center;
  }
}

// —— 手机卡片 ——
.cards {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
  padding: v.$sp-3;
}

.m-row {
  padding: 11px;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.m-row__top {
  display: flex;
  align-items: center;
  gap: v.$sp-2;

  b {
    font-size: v.$fs-sm;
  }
}

.dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px v.$sp-3;
  margin-top: v.$sp-2;
  font-size: v.$fs-xs;

  dt {
    color: v.$ink-400;
  }

  dd {
    margin: 0;
    font-weight: 600;
    text-align: right;
  }
}

// —— 说明条 ——
.alert {
  display: flex;
  gap: v.$sp-2;
  align-items: flex-start;
  padding: 11px 13px;
  border: 1px solid;
  border-radius: v.$r-md;
  font-size: v.$fs-sm;

  &--info {
    background: v.$info-bg;
    border-color: v.$info-line;
    color: #154882;
  }
}

.alert__i {
  flex: none;
  font-weight: 800;
  line-height: 1.3;
}

// —— 响应式 ——
@include bp.tablet {
  .kpis {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .two {
    grid-template-columns: 1fr;
  }
}

@include bp.mobile {
  .kpis {
    // PRD 10.2：手机端指标卡两列
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: v.$sp-2;
  }

  .kpi {
    padding: 11px;
  }

  .kpi__v {
    font-size: 1.25rem;
  }

  .two {
    grid-template-columns: 1fr;
  }

  .page-head__actions {
    width: 100%;

    :deep(.el-button),
    :deep(.el-radio-group) {
      flex: 1;
      min-height: v.$touch-target;
    }
  }

  .legend {
    display: none;
  }

  // FR-RWD-06 / PRD 10.4：所有可点击元素 ≥44×44。
  // 「按最低价排序」在窄屏提到 44px 高（桌面端保持 28px 紧凑排版）。
  .linkbtn {
    min-width: v.$touch-target;
    min-height: v.$touch-target;
  }
}
</style>
