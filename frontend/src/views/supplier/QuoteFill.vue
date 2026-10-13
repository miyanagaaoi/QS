<script setup>
/**
 * QuoteFill — 供货商报价填报页（核心，设计稿 03-3 / 03-4 / 03-5）
 * ===========================================================================
 * 覆盖的硬需求：
 *  FR-RWD-17 手机端一物料一卡片，默认只展开「含税单价」
 *  FR-RWD-18 单价 type="text" + inputmode="decimal"（避免部分安卓丢小数点）
 *  FR-RWD-19 底部吸底栏常显「已填 x/y 行」+ 保存 + 提交报价
 *  FR-RWD-20 提交前确认：未填则列出未填行并**阻断提交**
 *  FR-RWD-21 保存/提交成功顶部 Toast + 顶栏状态同步更新
 *  FR-RWD-22 行附件支持拍照 + 相册，上传前 canvas 压缩 ≤2MB
 *  FR-RWD-23 弱网/超时(15s) 不清空已填内容，给失败原因 + 「重试」
 *  FR-RWD-24 本地草稿：输入变更本地暂存，重进提示是否恢复
 *  FR-RWD-25 <24h 醒目提示；剩余 0 转只读
 *  FR-RWD-31 >10 行按每 10 行分段；底部计数**始终按整单**
 *  FR-SUP-06/07 顶部固定单据信息；物料信息只读
 *  FR-SUP-08/09 保存允许部分行；提交校验全行已填且截止前可改
 *  FR-SUP-11 截止后只读：输入 disabled，底部栏替换为说明条
 *  越权红线：页面只渲染本公司报价，无他方报价/最低价（PRD 3.3）
 *
 * 与基座的边界：只使用 src/api、src/components、src/composables 的公开导出，
 * 不修改也不新增基座文件。保存/提交需要 15s 超时与自管错误条，因此直接用
 * request.js 的 request()（同一个 HTTP 出口）而不是 api/supplier.js 的薄封装
 * —— 后者不接受 timeout/silent 参数。
 *
 * 接口（实测 + openapi 交叉核对，详见 quoteModel.js 头部）：
 *  GET  /api/supplier/rfqs/{rfq_id}        → SupplierRfqDetail
 *  PUT  /api/supplier/rfqs/{rfq_id}/quotes → 保存 & 提交（body.submit；本页统一走这一条）
 *  POST /api/supplier/rfqs/{rfq_id}/submit → 同一逻辑的便捷别名（已存在，强制 submit=True），本页未使用
 * ===========================================================================
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { CODE, request } from '@/api/request'
import { getSupplierRfq } from '@/api/supplier'
import StickyBar from '@/components/StickyBar.vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatRemaining } from '@/composables/useFormat'

import MaterialCard from './components/MaterialCard.vue'
import QuoteTable from './components/QuoteTable.vue'
import SubmitConfirmSheet from './components/SubmitConfirmSheet.vue'
import SupplierAppBar from './components/SupplierAppBar.vue'
import SupplierToast from './components/SupplierToast.vue'
import {
  QUOTE_REQUEST_TIMEOUT,
  SEGMENT_SIZE,
  SUPPLIER_ROUTES,
  applyDraft,
  arrivalMaxDate,
  buildSavePayload,
  buildSegments,
  createCountdown,
  createRows,
  draftHasContent,
  draftKey,
  formatRemainingCompact,
  formatServerDateTime,
  formatServerDateTimeShort,
  isRowFilled,
  localDateISO,
  resolveReadonly,
  sumFilled,
  toDraft,
  validateForSubmit,
} from './quoteModel'

defineOptions({ name: 'SupplierQuoteFill' })

const props = defineProps({
  /** 路由 props 传参优先；否则读 route.params.id（兼容 /supplier/quotes/:id） */
  rfqId: { type: [String, Number], default: '' },
})

const route = useRoute()
const router = useRouter()
const { isMobile, isDesktop } = useBreakpoint()

const rfqId = computed(() => String(props.rfqId || route.params.id || route.params.rfqId || ''))

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const loading = ref(true)
const loadError = ref('')
const detail = ref(null)
const rows = ref([])

/** 乐观锁基准：打开页面时的 assignment.updated_at（后端 PUT 返回最新 detail 后刷新） */
const baseUpdatedAt = ref(null)
const clock = ref(null)
const leftSeconds = ref(null)

const segmentIndex = ref(0)
const saving = ref(false)
const submitting = ref(false)
const saveError = ref('')
const saveErrorAction = ref('retry')
const lastWasSubmit = ref(false)
const conflict = ref(false)
const confirmVisible = ref(false)
const draftNotice = ref(null)
const toast = ref({ visible: false, type: 'success', message: '', actionText: '', duration: 2600 })
let toastActionHandler = null

function showToast(message, type = 'success', options = {}) {
  toast.value = {
    visible: true,
    type,
    message,
    actionText: options.actionText || '',
    duration: options.duration ?? (type === 'error' ? 0 : 2600),
  }
  toastActionHandler = options.onAction || null
}

function hideToast() {
  toast.value = { ...toast.value, visible: false }
  toastActionHandler = null
}

function onToastAction() {
  const handler = toastActionHandler
  hideToast()
  if (handler) handler()
}

// ---------------------------------------------------------------------------
// 派生状态
// ---------------------------------------------------------------------------
const total = computed(() => rows.value.length)
const stats = computed(() => sumFilled(rows.value))
const filledCount = computed(() => stats.value.filled)
const missingSeqs = computed(() => rows.value.filter((row) => !isRowFilled(row)).map((row) => row.seq))

const segments = computed(() => buildSegments(total.value))
/** >10 行才分段（FR-RWD-31：明细 ≤10 行时不分段） */
const useSegments = computed(() => total.value > SEGMENT_SIZE)
const currentSegment = computed(() => {
  if (!useSegments.value) return null
  return segments.value[segmentIndex.value] || segments.value[0] || null
})

/** 手机端只渲染当前段；平板/桌面表格一屏更长，直接渲染全部行 */
const mobileRows = computed(() => {
  const segment = currentSegment.value
  if (!segment) return rows.value
  return rows.value.slice(segment.from - 1, segment.to)
})
const tableRows = computed(() => rows.value)

const segmentMissingSeqs = computed(() => {
  const segment = currentSegment.value
  if (!segment) return []
  return rows.value
    .filter((row) => row.seq >= segment.from && row.seq <= segment.to && !isRowFilled(row))
    .map((row) => row.seq)
})
const segmentMissingSet = computed(() => new Set(segmentMissingSeqs.value))

const readonly = computed(() => resolveReadonly(detail.value, leftSeconds.value))
const isQuoted = computed(() => detail.value?.my_status === 'quoted')
const deadlineText = computed(() => formatServerDateTime(detail.value?.deadline))
const minDate = computed(() => localDateISO())
const maxDate = computed(() => arrivalMaxDate(detail.value?.deadline))
const urgent = computed(
  () => !readonly.value && leftSeconds.value !== null && leftSeconds.value > 0 && leftSeconds.value <= 24 * 3600,
)

const appBarBadge = computed(() => {
  if (readonly.value) return '已截止'
  if (isQuoted.value) return '已提交'
  if (leftSeconds.value === null) return ''
  return `剩余 ${formatRemainingCompact(leftSeconds.value)}`
})

const appBarBadgeTone = computed(() => {
  if (readonly.value) return 'default'
  if (isQuoted.value) return 'ok'
  if (leftSeconds.value !== null && leftSeconds.value <= 24 * 3600) return 'danger'
  return 'default'
})

/** 草稿提示（FR-RWD-24） */
const draftNoticeText = computed(() => {
  if (!draftNotice.value) return ''
  const savedAt = formatServerDateTimeShort(draftNotice.value.savedAt)
  const stale = draftNotice.value.stale ? '（服务端数据已更新，恢复将以本机内容为准）' : ''
  return `检测到未提交的草稿，保存于 ${savedAt}${stale}`
})

// ---------------------------------------------------------------------------
// 倒计时（以后端 remaining_seconds 为基准做本地漂移，不用本地解析 deadline）
// ---------------------------------------------------------------------------
let tickTimer = null

function startClock() {
  stopClock()
  tickTimer = setInterval(() => {
    if (clock.value) leftSeconds.value = clock.value.left()
  }, 10000)
}

function stopClock() {
  if (tickTimer) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}

// ---------------------------------------------------------------------------
// 本地草稿
// ---------------------------------------------------------------------------
function readDraft() {
  try {
    const raw = window.localStorage.getItem(draftKey(rfqId.value))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function persistDraft() {
  try {
    if (!rfqId.value) return
    const draft = toDraft(rows.value, baseUpdatedAt.value)
    if (!draftHasContent(draft)) {
      window.localStorage.removeItem(draftKey(rfqId.value))
      return
    }
    window.localStorage.setItem(draftKey(rfqId.value), JSON.stringify(draft))
  } catch {
    /* 隐私模式 / 存储禁用：静默降级，不影响填报 */
  }
}

function clearDraft() {
  try {
    window.localStorage.removeItem(draftKey(rfqId.value))
  } catch {
    /* 忽略 */
  }
  draftNotice.value = null
}

let draftTimer = null

function scheduleDraft() {
  if (draftTimer) clearTimeout(draftTimer)
  draftTimer = setTimeout(persistDraft, 1200)
}

function restoreDraft() {
  const draft = readDraft()
  if (draft) applyDraft(rows.value, draft)
  draftNotice.value = null
  showToast('已恢复本机草稿内容', 'success')
}

function dismissDraft() {
  clearDraft()
  showToast('已忽略本机草稿', 'info')
}

// ---------------------------------------------------------------------------
// 加载
// ---------------------------------------------------------------------------
function applyDetail(data, { detectDraft = false } = {}) {
  detail.value = data
  baseUpdatedAt.value = data?.updated_at || null
  rows.value = createRows(data)
  clock.value = createCountdown(data?.remaining_seconds ?? null)
  leftSeconds.value = clock.value.left()
  segmentIndex.value = Math.min(segmentIndex.value, Math.max(0, buildSegments(rows.value.length).length - 1))
  if (detectDraft) {
    const draft = readDraft()
    if (draftHasContent(draft)) {
      draftNotice.value = {
        savedAt: draft.savedAt,
        stale: Boolean(draft.updatedAt && baseUpdatedAt.value && draft.updatedAt !== baseUpdatedAt.value),
      }
    } else {
      draftNotice.value = null
    }
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await getSupplierRfq(rfqId.value)
    applyDetail(data, { detectDraft: true })
  } catch (error) {
    loadError.value = error?.message || '报价单加载失败'
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// 保存 / 提交
// ---------------------------------------------------------------------------
function handleSaveError(error, submit) {
  const code = error?.code
  if (code === CODE.QUOTE_CLOSED) {
    saveError.value = error?.message || '报价已截止，无法修改'
    saveErrorAction.value = 'reload'
    showToast('报价已截止，页面已转为只读', 'warn')
    clock.value = createCountdown(0)
    leftSeconds.value = 0
    return
  }
  if (code === CODE.CONFLICT) {
    conflict.value = true
    saveErrorAction.value = 'override'
    saveError.value = `${error?.message || '该报价单已被其他会话修改，请刷新后重试'}；已填内容已保留在本机。`
    return
  }
  // 弱网 / 超时 / 服务端异常：**不清空已填内容**，只给原因 + 重试（FR-RWD-23）
  saveError.value = error?.message || (submit ? '提交失败，请检查网络后重试' : '保存失败，请检查网络后重试')
  saveErrorAction.value = 'retry'
}

async function doSave(submit) {
  if (readonly.value) {
    showToast('报价已截止，无法修改', 'warn')
    return
  }
  if (saving.value) return
  lastWasSubmit.value = Boolean(submit)
  const payload = buildSavePayload(rows.value, {
    submit: Boolean(submit),
    // 冲突后由用户确认「以本机内容覆盖」时不带基准，跳过乐观锁比对
    expectedUpdatedAt: conflict.value ? null : baseUpdatedAt.value,
  })
  if (!payload.lines.length && !submit) {
    showToast('没有需要保存的修改', 'info')
    return
  }

  saving.value = true
  submitting.value = Boolean(submit)
  saveError.value = ''
  try {
    const data = await request({
      url: `/supplier/rfqs/${rfqId.value}/quotes`,
      method: 'put',
      data: payload,
      timeout: QUOTE_REQUEST_TIMEOUT, // 15s（FR-RWD-23 / PRD 10.5）
      silent: true, // 错误由页面错误条统一呈现，避免与 ElMessage 重复
    })
    conflict.value = false
    saveErrorAction.value = 'retry'
    applyDetail(data)
    clearDraft()
    if (submit) {
      showToast('报价已提交成功，截止前仍可修改', 'success')
    } else {
      showToast(`已保存，本单已填 ${stats.value.filled}/${stats.value.total} 行`, 'success')
    }
  } catch (error) {
    handleSaveError(error, submit)
  } finally {
    saving.value = false
    submitting.value = false
  }
}

function retrySave() {
  const wasSubmit = saveErrorAction.value === 'override' ? true : lastWasSubmit.value
  doSave(wasSubmit)
}

function reloadAfterClosed() {
  load()
}

/** 提交入口：先本地校验，未填则弹层列出并阻断（FR-RWD-20） */
function openSubmit() {
  if (readonly.value) return
  confirmVisible.value = true
}

function onConfirmSubmit() {
  confirmVisible.value = false
  doSave(true)
}

function onSaveDraftFromSheet() {
  confirmVisible.value = false
  doSave(false)
}

// ---------------------------------------------------------------------------
// 分段与跳转
// ---------------------------------------------------------------------------
function goSegment(index) {
  if (index < 0 || index >= segments.value.length) return
  segmentIndex.value = index
  scrollToTop()
}

function scrollToTop() {
  nextTick(() => {
    const anchor = document.getElementById('qf-lines')
    if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'start' })
    else window.scrollTo({ top: 0, behavior: 'smooth' })
  })
}

function jumpToSeq(seq) {
  confirmVisible.value = false
  const index = Math.max(0, Math.floor((Number(seq) - 1) / SEGMENT_SIZE))
  segmentIndex.value = Math.min(index, Math.max(0, segments.value.length - 1))
  nextTick(() => {
    const el = document.getElementById(`line-${seq}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

function jumpToNextMissing() {
  const next = segmentMissingSeqs.value[0] ?? missingSeqs.value[0]
  if (next === undefined) return
  if (next >= (currentSegment.value?.from ?? 1) && next <= (currentSegment.value?.to ?? total.value)) {
    nextTick(() => {
      const el = document.getElementById(`line-${next}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return
  }
  jumpToSeq(next)
}

function onCardPatch(row, patch) {
  Object.assign(row, patch)
}

function onTablePatch({ row, patch }) {
  Object.assign(row, patch)
}

function goBack() {
  router.push(SUPPLIER_ROUTES.list)
}

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------
onMounted(() => {
  if (!rfqId.value) {
    loading.value = false
    loadError.value = '缺少询价单编号，请从「待报价」列表进入'
    return
  }
  load()
  startClock()
})

onBeforeUnmount(() => {
  stopClock()
  if (draftTimer) clearTimeout(draftTimer)
  // 切后台 / 离开页面前落地草稿，避免丢数据（FR-RWD-23、FR-RWD-24）
  persistDraft()
})

watch(rows, () => {
  if (!loading.value) scheduleDraft()
}, { deep: true })
</script>

<template>
  <div class="qf">
    <SupplierAppBar
      :title="readonly ? '报价单详情' : '填写报价'"
      :tone="readonly ? 'closed' : 'brand'"
      :badge="appBarBadge"
      :badge-tone="appBarBadgeTone"
      back
      @back="goBack"
    />

    <SupplierToast
      :visible="toast.visible"
      :type="toast.type"
      :message="toast.message"
      :action-text="toast.actionText"
      :duration="toast.duration"
      @action="onToastAction"
      @close="hideToast"
    />

    <main class="qf__body">
      <!-- 骨架屏 -->
      <template v-if="loading">
        <div v-for="n in 3" :key="`sk-${n}`" class="skel">
          <span class="skel__line is-title" />
          <span class="skel__line is-sub" />
          <span class="skel__line is-input" />
        </div>
      </template>

      <!-- 加载失败 -->
      <div v-else-if="loadError" class="alert is-danger">
        <span class="alert__i" aria-hidden="true">!</span>
        <div class="alert__body">
          <b>{{ loadError }}</b>
          <p class="alert__sub">请检查网络后重试；已填写的内容不会丢失。</p>
          <button type="button" class="alert__action" @click="load">重试</button>
        </div>
      </div>

      <!-- 空状态（PRD 10.3 第 8 条） -->
      <div v-else-if="!total" class="qf__empty">
        <p class="qf__empty-title">该询价单没有需要报价的物料</p>
        <p class="qf__empty-desc">请联系采购方确认单据内容。</p>
        <button type="button" class="btn btn-secondary" @click="goBack">返回待报价列表</button>
      </div>

      <template v-else>
        <!-- 顶部单据信息（FR-SUP-06） -->
        <section class="qf__doc">
          <h2 class="qf__doc-title">{{ detail.title }}</h2>
          <p class="qf__doc-meta">
            <span class="num">{{ detail.rfq_no }}</span>
            <em>·</em>
            <span v-if="detail.project">{{ detail.project }}</span>
            <em v-if="detail.project">·</em>
            <span>截止 {{ deadlineText }}</span>
          </p>
          <p class="qf__doc-stats">
            <span>共 <b class="num">{{ total }}</b> 行</span>
            <span>已填 <b class="num">{{ filledCount }}/{{ total }}</b></span>
            <span v-if="detail.submitted_at">提交于 <b class="num">{{ formatServerDateTimeShort(detail.submitted_at) }}</b></span>
          </p>
          <p v-if="detail.remark" class="qf__doc-remark">采购方备注：{{ detail.remark }}</p>
        </section>

        <!-- 截止后只读说明（FR-SUP-11 / 设计稿 F 屏） -->
        <div v-if="readonly" class="alert is-warn">
          <span class="alert__i" aria-hidden="true">!</span>
          <div class="alert__body">
            <b>本单已于 {{ deadlineText }} 截止</b>，报价已锁定，不能再修改。以下为你提交的报价内容。
          </div>
        </div>

        <!-- <24h 醒目提示（FR-RWD-25） -->
        <div v-else-if="urgent" class="alert is-warn">
          <span class="alert__i" aria-hidden="true">!</span>
          <div class="alert__body">仅剩 {{ formatRemaining(leftSeconds) }}，请尽快提交</div>
        </div>

        <!-- 本地草稿恢复提示（FR-RWD-24） -->
        <div v-if="draftNotice && !readonly" class="alert is-info">
          <span class="alert__i" aria-hidden="true">i</span>
          <div class="alert__body">
            {{ draftNoticeText }}
            <div class="alert__actions">
              <button type="button" class="alert__action is-primary" @click="restoreDraft">恢复草稿</button>
              <button type="button" class="alert__action" @click="dismissDraft">忽略</button>
            </div>
          </div>
        </div>

        <!-- 保存/提交失败：原因 + 重试（FR-RWD-23） -->
        <div v-if="saveError" class="alert is-danger">
          <span class="alert__i" aria-hidden="true">!</span>
          <div class="alert__body">
            <b>{{ lastWasSubmit ? '提交失败：' : '保存失败：' }}{{ saveError }}</b>
            <p class="alert__sub">你填写的内容已保留，请检查网络后重试。</p>
            <div class="alert__actions">
              <button
                v-if="saveErrorAction === 'reload'"
                type="button"
                class="alert__action"
                @click="reloadAfterClosed"
              >
                刷新页面数据
              </button>
              <button v-else type="button" class="alert__action" @click="retrySave">
                {{ saveErrorAction === 'override' ? '以本机内容覆盖并重试' : '重试' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 分段导航（>10 行，FR-RWD-31） -->
        <template v-if="useSegments">
          <nav class="seg" aria-label="分段导航">
            <span class="seg__info">
              第 <b class="num">{{ currentSegment.from }}~{{ currentSegment.to }}</b> 行 / 共
              <b class="num">{{ total }}</b> 行
            </span>
            <span class="seg__nav">
              <button
                type="button"
                class="seg__btn"
                :disabled="segmentIndex === 0"
                aria-label="上一段"
                @click="goSegment(segmentIndex - 1)"
              >
                ‹
              </button>
              <button
                type="button"
                class="seg__btn"
                :disabled="segmentIndex >= segments.length - 1"
                aria-label="下一段"
                @click="goSegment(segmentIndex + 1)"
              >
                ›
              </button>
            </span>
          </nav>

          <p v-if="isMobile" class="seg__stat">
            本段 {{ currentSegment.to - currentSegment.from + 1 }} 行中有
            <b :class="{ 'is-danger': segmentMissingSeqs.length > 0 }">{{ segmentMissingSeqs.length }} 行未填</b>
            · 全单已填 <b class="num">{{ filledCount }}/{{ total }}</b>
            <button
              v-if="segmentMissingSeqs.length > 0"
              type="button"
              class="seg__jump"
              @click="jumpToNextMissing"
            >
              跳到未填行
            </button>
          </p>

          <div v-if="isMobile && segments.length > 2" class="seg__jump-list">
            <button
              v-for="segment in segments"
              :key="segment.index"
              type="button"
              class="seg__chip"
              :class="{ 'is-active': segment.index === segmentIndex }"
              @click="goSegment(segment.index)"
            >
              {{ segment.label }}
            </button>
          </div>
        </template>

        <!-- 手机：物料卡片（当前段） -->
        <section v-if="isMobile" id="qf-lines" class="qf__lines">
          <MaterialCard
            v-for="row in mobileRows"
            :id="`line-${row.seq}`"
            :key="row.lineUid"
            :row="row"
            :disabled="readonly"
            :highlight-missing="segmentMissingSet.has(row.seq)"
            :min-date="minDate"
            :max-date="maxDate"
            @patch="onCardPatch(row, $event)"
          />
        </section>

        <!-- 平板/桌面：表格形态（平板 6 列，桌面全列） -->
        <section v-else id="qf-lines" class="qf__table">
          <QuoteTable
            :rows="tableRows"
            :variant="isDesktop ? 'desktop' : 'tablet'"
            :disabled="readonly"
            :min-date="minDate"
            :max-date="maxDate"
            @patch="onTablePatch"
          />
        </section>
      </template>
    </main>

    <!-- 底部吸底操作栏（FR-RWD-19） -->
    <StickyBar v-if="!readonly && total > 0">
      <span class="qf__count">
        <span class="qf__count-label">已填</span>
        <b class="num">{{ filledCount }} / {{ total }}</b>
      </span>
      <template #actions>
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="saving"
          @click="doSave(false)"
        >
          {{ saving && !submitting ? '保存中…' : '保存' }}
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="saving || submitting"
          @click="openSubmit"
        >
          {{ submitting ? '提交中…' : '提交报价' }}
        </button>
      </template>
    </StickyBar>

    <!-- 截止后底部栏替换为说明条（FR-SUP-11 / 设计稿 F 屏） -->
    <div v-else-if="total > 0" class="qf__closedbar">
      报价已于 {{ deadlineText }} 截止，不可修改
    </div>

    <!-- 提交前确认（设计稿 C 屏，未填则阻断） -->
    <SubmitConfirmSheet
      :visible="confirmVisible"
      :rows="rows"
      :submitting="submitting"
      @jump="jumpToSeq"
      @save-draft="onSaveDraftFromSheet"
      @cancel="confirmVisible = false"
      @confirm="onConfirmSubmit"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.qf {
  min-height: 100vh;
  background: v.$surface-sunken;
}

.qf__body {
  max-width: 720px;
  // 水平内边距由外层 SupplierLayout（task-1）统一提供，这里只留纵向节奏，
  // 避免"布局 12px + 页面 12px"叠成 24px 把手机端挤窄（390px 可用宽度本就紧张）。
  // 底部空间同理由 SupplierLayout 为 StickyBar 预留，页面不再重复计算。
  padding: 0 0 v.$sp-6;
  margin: 0 auto;
}

// —— 单据信息卡 ——
.qf__doc {
  padding: 10px v.$sp-3;
  margin-bottom: 10px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.qf__doc-title {
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$ink-900;
  overflow-wrap: anywhere;
}

.qf__doc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 3px 0 0;
  font-size: 11.5px;
  color: v.$ink-400;

  em {
    font-style: normal;
  }
}

.qf__doc-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin: 9px 0 0;
  padding-top: 9px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
  border-top: 1px dashed v.$line;

  b {
    color: v.$ink-900;
  }
}

.qf__doc-remark {
  margin: 6px 0 0;
  padding-top: 6px;
  font-size: 11.5px;
  line-height: 1.5;
  color: v.$info;
  border-top: 1px dashed v.$line;
}

// —— 提示条 ——
.alert {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 11px v.$sp-3;
  margin-bottom: 10px;
  font-size: v.$fs-xs;
  line-height: 1.5;
  border: 1px solid;
  border-radius: v.$r-md;

  &.is-warn {
    color: #7a4208;
    background: v.$warn-bg;
    border-color: v.$warn-line;
  }

  &.is-danger {
    color: #8e1b12;
    background: v.$danger-bg;
    border-color: v.$danger-line;
  }

  &.is-info {
    color: #154882;
    background: v.$info-bg;
    border-color: v.$info-line;
  }
}

.alert__i {
  flex: none;
  font-weight: 800;
}

.alert__body {
  flex: 1;
  min-width: 0;
}

.alert__sub {
  margin: 4px 0 0;
  opacity: 0.85;
}

.alert__actions {
  display: flex;
  flex-wrap: wrap;
  gap: v.$sp-2;
  margin-top: 9px;
}

.alert__action {
  min-height: 34px;
  padding: 0 12px;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: currentColor;
  background: #fff;
  border: 1px solid currentColor;
  border-radius: v.$r-md;
  cursor: pointer;

  &.is-primary {
    color: #fff;
    background: v.$brand-700;
    border-color: v.$brand-700;
  }
}

// —— 分段导航 ——
.seg {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  padding: v.$sp-2 10px;
  margin-bottom: 10px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.seg__info {
  font-size: 11.5px;
  color: v.$ink-500;

  b {
    color: v.$ink-900;
  }
}

.seg__nav {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.seg__btn {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  font-family: inherit;
  font-size: v.$fs-body;
  color: v.$ink-700;
  background: #fff;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;
  cursor: pointer;

  &:disabled {
    color: v.$ink-300;
    background: v.$surface-sunken;
    cursor: not-allowed;
  }
}

.seg__stat {
  margin: 0 0 8px 2px;
  font-size: 11.5px;
  color: v.$ink-400;

  b {
    color: v.$ink-700;

    &.is-danger {
      color: v.$danger;
    }
  }
}

.seg__jump {
  min-height: 26px;
  margin-left: v.$sp-2;
  padding: 0 8px;
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 600;
  color: v.$brand-700;
  background: transparent;
  border: 1px solid v.$brand-100;
  border-radius: v.$r-md;
  cursor: pointer;
}

.seg__jump-list {
  display: flex;
  gap: 5px;
  margin-bottom: 10px;
  padding-bottom: 2px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.seg__chip {
  flex: none;
  min-height: 30px;
  padding: 0 9px;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-500;
  background: #fff;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
  cursor: pointer;

  &.is-active {
    color: #fff;
    background: v.$brand-700;
    border-color: v.$brand-700;
  }
}

.qf__lines,
.qf__table {
  min-width: 0;
}

// —— 吸底栏内容 ——
.qf__count {
  display: block;

  b {
    display: block;
    font-size: v.$fs-lg;
    color: v.$ink-900;
    letter-spacing: -0.02em;
  }
}

.qf__count-label {
  font-size: 10.5px;
  color: v.$ink-500;
}

.qf__closedbar {
  position: sticky;
  bottom: 0;
  z-index: v.$z-sticky - 100;
  padding: 12px v.$sp-3 calc(12px + env(safe-area-inset-bottom, 0px));
  font-size: v.$fs-xs;
  color: v.$ink-500;
  text-align: center;
  background: v.$surface-sunken;
  border-top: 1px solid v.$line;
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

  &:disabled {
    cursor: not-allowed;
    opacity: 0.7;
  }
}

.btn-primary {
  color: #fff;
  background: v.$brand-700;
  border-color: v.$brand-700;

  &:disabled {
    color: v.$ink-300;
    background: v.$surface-sunken;
    border-color: v.$line;
    opacity: 1;
  }
}

.btn-secondary {
  color: v.$ink-700;
  background: v.$surface;
  border-color: v.$line-strong;
}

// —— 骨架屏 / 空状态 ——
.skel {
  padding: v.$sp-3;
  margin-bottom: 10px;
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
    width: 55%;
    height: 15px;
  }

  &.is-sub {
    width: 72%;
    height: 11px;
    margin-top: 8px;
  }

  &.is-input {
    width: 100%;
    height: 44px;
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

.qf__empty {
  padding: v.$sp-6 v.$sp-4;
  text-align: center;
}

.qf__empty-title {
  font-size: v.$fs-body;
  font-weight: 600;
  color: v.$ink-900;
}

.qf__empty-desc {
  margin: 6px 0 v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.qf__empty .btn {
  margin: 0 auto;
}

@include bp.tablet-up {
  .qf__body {
    max-width: 1180px;
    padding: 0 0 v.$sp-6;
  }

  .qf__doc {
    padding: v.$sp-3 v.$sp-4;
  }

  .seg__btn {
    width: 32px;
    height: 32px;
  }
}
</style>
