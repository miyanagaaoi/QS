<script setup>
/**
 * QuoteList — 供货商「待报价」列表（设计稿 03-2 / FR-SUP-01~05 / FR-RWD-16、25）
 * ---------------------------------------------------------------------------
 * 手机端卡片列表：单据名称 / 状态徽标 / 单号 · 项目 · 行数 / 截止剩余时间 / 我的报价状态 x÷y 行 / 主按钮。
 * 分区：进行中（待报价 · 报价中 · 已提交）在上，已截止（仅可查看自己的报价）在下。
 * <24h：整卡红色左边框 + 红色加粗倒计时（FR-RWD-25）。
 *
 * 越权红线（PRD 3.3 / FR-SUP-05）：本页只渲染 /supplier/rfqs 返回的"我的"字段，
 * 页面不出现他方报价、当前最低价、其他供货商状态等任何信息。
 *
 * 倒计时不要用本地解析 deadline（后端 deadline 是 UTC naive，会差 8 小时）；
 * 统一用接口给的 remaining_seconds 做本地单调漂移，实测见 views/supplier/quoteModel.js 头部注释。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listSupplierRfqs } from '@/api/supplier'
import StatusBadge from '@/components/StatusBadge.vue'
import { formatRemaining } from '@/composables/useFormat'

import SupplierAppBar from './components/SupplierAppBar.vue'
import SupplierUserMenu from './components/SupplierUserMenu.vue'
import {
  SUPPLIER_ROUTES,
  createCountdown,
  formatServerDateTimeShort,
  myStatusBadge,
  primaryActionLabel,
  remainingTone,
} from './quoteModel'

defineOptions({ name: 'SupplierQuoteList' })

const router = useRouter()

const loading = ref(true)
const loadError = ref('')
const items = ref([])
/** all | pending | quoted（设计稿顶部两个统计 chip） */
const filter = ref('all')

/** 倒计时按 10s 刷新即可（展示粒度到分钟） */
const tick = ref(0)
let timer = null
const countdowns = new Map()

async function fetchList() {
  loading.value = true
  loadError.value = ''
  try {
    // 只信任服务端身份：绝不传 supplier_id（PRD 7.3 安全约束）
    const data = await listSupplierRfqs({ page: 1, page_size: 100 })
    items.value = Array.isArray(data?.items) ? data.items : []
    countdowns.clear()
    items.value.forEach((item) => {
      countdowns.set(item.rfq_id, createCountdown(item.remaining_seconds))
    })
  } catch (error) {
    loadError.value = error?.message || '待报价列表加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchList()
  timer = setInterval(() => {
    tick.value += 1
  }, 10000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

function leftOf(item) {
  const clock = countdowns.get(item.rfq_id)
  if (clock) return clock.left()
  return item.remaining_seconds ?? null
}

const decorated = computed(() => {
  void tick.value
  return items.value.map((item) => {
    const left = leftOf(item)
    const closed = item.status === 'closed' || (left !== null && Number(left) <= 0)
    const badge = myStatusBadge(item.my_status)
    const total = Number(item.line_count || 0)
    const filled = Number(item.quoted_line_count || 0)
    return {
      raw: item,
      id: item.rfq_id,
      left,
      closed,
      badge,
      total,
      filled,
      percent: total > 0 ? Math.round((filled / total) * 100) : 0,
      tone: closed ? 'closed' : remainingTone(left),
    }
  })
})

const openItems = computed(() => decorated.value.filter((item) => !item.closed))
const closedItems = computed(() => decorated.value.filter((item) => item.closed))
const pendingCount = computed(() => decorated.value.filter((item) => item.raw.my_status === 'pending').length)
const quotedCount = computed(() => decorated.value.filter((item) => item.raw.my_status === 'quoted').length)

const visibleOpenItems = computed(() => {
  if (filter.value === 'all') return openItems.value
  return openItems.value.filter((item) => item.raw.my_status === filter.value)
})

function toggleFilter(key) {
  filter.value = filter.value === key ? 'all' : key
}

function remainingText(item) {
  if (item.closed) return '已截止'
  const value = formatRemaining(item.left)
  return value === '已截止' ? '已截止' : `剩余 ${value}`
}

function progressClass(item) {
  if (item.raw.my_status === 'quoted') return 'is-ok'
  if (item.raw.my_status === 'partial') return 'is-warn'
  return ''
}

function rightMetaText(item) {
  if (item.closed) return `已报价 ${item.filled}/${item.total} 行`
  if (item.raw.my_status === 'quoted') return '已提交，截止前仍可修改'
  if (item.raw.my_status === 'partial') {
    return item.raw.last_saved_at ? `保存于 ${formatServerDateTimeShort(item.raw.last_saved_at)}` : ''
  }
  return `已填 ${item.filled}/${item.total} 行`
}

function openFill(id) {
  router.push(SUPPLIER_ROUTES.fill(id))
}
</script>

<template>
  <div class="ql">
    <SupplierAppBar title="待报价" :badge="`${openItems.length} 张`">
      <template #right>
        <SupplierUserMenu />
      </template>
    </SupplierAppBar>

    <main class="ql__body">
      <!-- 顶部统计 chip：待报价 / 已报价（设计稿 03-2） -->
      <div class="ql__chips" role="group" aria-label="按我的报价状态筛选">
        <button
          type="button"
          class="chip"
          :class="{ 'is-active': filter === 'pending' }"
          :aria-pressed="filter === 'pending'"
          @click="toggleFilter('pending')"
        >
          <span class="chip__dot" aria-hidden="true" />待报价 {{ pendingCount }}
        </button>
        <button
          type="button"
          class="chip is-outline"
          :class="{ 'is-active': filter === 'quoted' }"
          :aria-pressed="filter === 'quoted'"
          @click="toggleFilter('quoted')"
        >
          <span class="chip__dot" aria-hidden="true" />已报价 {{ quotedCount }}
        </button>
        <button
          v-if="filter !== 'all'"
          type="button"
          class="chip is-clear"
          @click="filter = 'all'"
        >
          显示全部
        </button>
      </div>

      <!-- 失败态：可重试（FR-RWD-23） -->
      <div v-if="loadError" class="alert is-danger">
        <span class="alert__i" aria-hidden="true">!</span>
        <div class="alert__body">
          <b>{{ loadError }}</b>
          <p class="alert__sub">已填内容不受影响，请检查网络后重试。</p>
          <button type="button" class="alert__action" @click="fetchList">重试</button>
        </div>
      </div>

      <!-- 骨架屏（PRD 10.4：不用全屏遮罩转圈） -->
      <template v-if="loading">
        <div v-for="n in 3" :key="`sk-${n}`" class="skel">
          <span class="skel__line is-title" />
          <span class="skel__line is-sub" />
          <span class="skel__line is-bar" />
          <span class="skel__line is-btn" />
        </div>
      </template>

      <template v-else>
        <!-- 进行中 -->
        <section v-if="visibleOpenItems.length" class="ql__section">
          <article
            v-for="item in visibleOpenItems"
            :key="item.id"
            class="row-card"
            :class="{ 'is-urgent': item.tone === 'danger' }"
          >
            <div class="row-card__head">
              <h2 class="row-card__title">{{ item.raw.title }}</h2>
              <StatusBadge
                :status="item.raw.my_status"
                :label="item.badge.label"
                :tone="item.badge.tone"
              />
            </div>
            <p class="row-card__meta">
              <span class="num">{{ item.raw.rfq_no }}</span>
              <em>·</em><span>{{ item.raw.project || '—' }}</span>
              <em>·</em><span>{{ item.total }} 行</span>
            </p>

            <div v-if="item.raw.my_status !== 'pending'" class="prog">
              <span class="prog__bar" :class="progressClass(item)">
                <i :style="{ width: `${item.percent}%` }" />
              </span>
              <span class="prog__txt num">{{ item.filled }}/{{ item.total }} 行</span>
            </div>

            <div class="row-card__foot">
              <span class="row-card__left" :class="`is-${item.tone}`">{{ remainingText(item) }}</span>
              <span class="row-card__right num" :class="{ 'is-ok': item.raw.my_status === 'quoted' }">
                {{ rightMetaText(item) }}
              </span>
            </div>

            <button
              type="button"
              class="btn btn-block"
              :class="item.raw.my_status === 'quoted' ? 'btn-secondary' : 'btn-primary'"
              @click="openFill(item.id)"
            >
              {{ primaryActionLabel(item.raw.my_status) }}
            </button>
          </article>
        </section>

        <p v-else-if="filter !== 'all'" class="ql__empty-inline">
          没有「{{ filter === 'pending' ? '待报价' : '已报价' }}」的单据
        </p>

        <!-- 已截止（仅可查看自己的报价） -->
        <section v-if="closedItems.length" class="ql__section">
          <div class="ql__closed">
            <div class="ql__closed-head">已截止（仅可查看自己的报价）</div>
            <div v-for="item in closedItems" :key="`c-${item.id}`" class="ql__closed-row">
              <div class="ql__closed-info">
                <div class="ql__closed-title">{{ item.raw.title }}</div>
                <div class="ql__closed-sub">
                  <span class="num">{{ item.raw.rfq_no }}</span> · 已报价
                  <span class="num">{{ item.filled }}/{{ item.total }}</span> 行
                </div>
              </div>
              <button type="button" class="ql__link" @click="openFill(item.id)">查看</button>
            </div>
          </div>
        </section>

        <!-- 空状态 -->
        <div v-if="!openItems.length && !closedItems.length" class="ql__empty">
          <p class="ql__empty-title">暂无可报价的询价单</p>
          <p class="ql__empty-desc">采购方发布并分派给本公司后，单据会出现在这里。</p>
          <button type="button" class="btn btn-secondary" @click="fetchList">刷新</button>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.ql {
  min-height: 100vh;
  background: v.$surface-sunken;
}

.ql__body {
  // 水平内边距 / 底部安全区由外层 SupplierLayout（task-1）统一提供
  max-width: 720px;
  padding: 0;
  margin: 0 auto;
}

// —— 筛选 chip ——
.ql__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: v.$sp-3;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 4px 12px;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-700;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: 100px;
  cursor: pointer;

  &.is-active {
    color: #fff;
    background: v.$brand-700;
    border-color: v.$brand-700;
  }

  &.is-outline.is-active {
    color: v.$brand-800;
    background: v.$brand-50;
    border-color: v.$brand-100;
  }

  &.is-clear {
    color: v.$ink-500;
    background: transparent;
    border-color: transparent;
  }
}

.chip__dot {
  width: 5px;
  height: 5px;
  background: currentColor;
  border-radius: 50%;
}

// —— 列表卡片 ——
.ql__section {
  margin-bottom: v.$sp-2;
}

.row-card {
  padding: v.$sp-3;
  margin-bottom: 9px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;

  // <24h：整卡醒目（FR-RWD-25）
  &.is-urgent {
    border-left: 3px solid v.$danger;
  }
}

.row-card__head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-2;
}

.row-card__title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.4;
  color: v.$ink-900;
  overflow-wrap: anywhere;
}

.row-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 4px 0 0;
  font-size: 11.5px;
  color: v.$ink-500;

  em {
    font-style: normal;
    color: v.$ink-300;
  }
}

.prog {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-top: v.$sp-2;
}

.prog__bar {
  flex: 1;
  height: 5px;
  overflow: hidden;
  background: v.$line;
  border-radius: 100px;

  i {
    display: block;
    height: 100%;
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
  font-size: 11px;
  color: v.$ink-500;
}

.row-card__foot {
  display: flex;
  align-items: baseline;
  gap: v.$sp-2;
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px dashed v.$line;
}

.row-card__left {
  font-size: 11.5px;
  font-weight: 700;
  color: v.$ink-500;

  &.is-danger {
    color: v.$danger;
  }

  &.is-warn {
    font-weight: 600;
    color: v.$warn;
  }

  &.is-closed {
    font-weight: 500;
    color: v.$ink-400;
  }
}

.row-card__right {
  margin-left: auto;
  font-size: 11.5px;
  color: v.$ink-400;
  text-align: right;

  &.is-ok {
    font-weight: 600;
    color: v.$ok;
  }
}

// —— 按钮 ——
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: v.$touch-target;
  padding: 0 14px;
  font-family: inherit;
  font-size: v.$fs-sm;
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: v.$r-md;
  cursor: pointer;
}

.btn-block {
  width: 100%;
  margin-top: 10px;
}

.btn-primary {
  color: #fff;
  background: v.$brand-700;
  border-color: v.$brand-700;
}

.btn-secondary {
  color: v.$ink-700;
  background: v.$surface;
  border-color: v.$line-strong;
}

// —— 已截止分区 ——
.ql__closed {
  overflow: hidden;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.ql__closed-head {
  padding: 11px v.$sp-3;
  font-size: 11.5px;
  font-weight: 600;
  color: v.$ink-400;
  border-bottom: 1px solid v.$line-soft;
}

.ql__closed-row {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  padding: 11px v.$sp-3;

  & + & {
    border-top: 1px solid v.$line-soft;
  }
}

.ql__closed-info {
  flex: 1;
  min-width: 0;
}

.ql__closed-title {
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$ink-900;
  overflow-wrap: anywhere;
}

.ql__closed-sub {
  margin-top: 3px;
  font-size: 11.5px;
  color: v.$ink-400;
}

.ql__link {
  flex: none;
  min-height: v.$touch-target;
  padding: 0 10px;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$brand-700;
  background: transparent;
  border: none;
  cursor: pointer;
}

// —— 提示条 ——
.alert {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 11px v.$sp-3;
  margin-bottom: v.$sp-3;
  font-size: v.$fs-xs;
  line-height: 1.5;
  border: 1px solid;
  border-radius: v.$r-md;

  &.is-danger {
    color: #8e1b12;
    background: v.$danger-bg;
    border-color: v.$danger-line;
  }
}

.alert__i {
  flex: none;
  font-weight: 800;
}

.alert__body {
  flex: 1;
  min-width: 0;

  b {
    font-weight: 700;
  }
}

.alert__sub {
  margin: 4px 0 0;
  opacity: 0.85;
}

.alert__action {
  min-height: 32px;
  margin-top: 9px;
  padding: 0 12px;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$danger;
  background: #fff;
  border: 1px solid v.$danger-line;
  border-radius: v.$r-md;
  cursor: pointer;
}

// —— 骨架屏 ——
.skel {
  padding: v.$sp-3;
  margin-bottom: 9px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.skel__line {
  display: block;
  background: linear-gradient(90deg, v.$surface-hover, #e9ecf0, v.$surface-hover);
  background-size: 200% 100%;
  border-radius: v.$r-sm;
  animation: skel-shine 1.2s ease-in-out infinite;

  &.is-title {
    width: 62%;
    height: 14px;
  }

  &.is-sub {
    width: 78%;
    height: 11px;
    margin-top: 8px;
  }

  &.is-bar {
    width: 100%;
    height: 5px;
    margin-top: 12px;
  }

  &.is-btn {
    width: 100%;
    height: 40px;
    margin-top: 12px;
  }
}

@keyframes skel-shine {
  0% {
    background-position: 200% 0;
  }

  100% {
    background-position: -200% 0;
  }
}

// —— 空状态 ——
.ql__empty,
.ql__empty-inline {
  padding: v.$sp-6 v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$ink-500;
  text-align: center;
}

.ql__empty-title {
  font-size: v.$fs-body;
  font-weight: 600;
  color: v.$ink-900;
}

.ql__empty-desc {
  margin: 6px 0 v.$sp-4;
  color: v.$ink-400;
}

.ql__empty .btn {
  margin: 0 auto;
}

@include bp.tablet-up {
  .ql__body {
    max-width: 1040px;
  }

  .row-card {
    padding: v.$sp-4;
  }

  .row-card__title {
    font-size: v.$fs-body;
  }
}
</style>
