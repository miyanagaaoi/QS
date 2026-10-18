<script setup>
/**
 * RfqProgress.vue — 报价进度（催办）（设计稿 02-3）
 * ---------------------------------------------------------------------------
 * 路由：/purchase/rfq/:id
 *
 * PRD：FR-RFQ-13~16 / FR-RWD-11 / Q10（本期不做消息通知，本页承担全部催办职能）
 *  - 顶部警示条：还有 N 家未报价 + 一键复制未报价名单与联系方式
 *  - 桌面表格 / 手机卡片（催办主场景，完整可用），未报价分组置顶
 *  - 底部汇总：已报价 X 家 · 报价中 Y 家 · 未报价 Z 家（已报价家数按"提交报价"计）
 *  - 【task-11 新需求】已发布且**未截止**时可「追加供货商」：
 *    只追加不删除、不影响已有报价；候选只列尚未被分派的供货商档案。
 *    桌面 el-dialog / 手机 el-drawer(btt) 共用 AppendSuppliersPanel。
 *
 * 字段来源（已 curl 核对 backend/app/schemas.py）：
 *  GET /rfqs/{id}          → RfqDetail：rfq_no/title/project/status/deadline/lines[]./assignees[]
 *  GET /rfqs/{id}/progress → AssigneeOut[]（裸数组，不是 PageData）：
 *      supplier_id / supplier_name / contact_name / contact_phone /
 *      status(pending|partial|quoted) / line_count / quoted_line_count /
 *      last_saved_at / submitted_at
 *
 * 已知契约缺口：AssigneeOut 没有"是否打开过填报页"字段，设计稿里的
 * 「未打开填报页 / 已打开未保存」二级区分无法精确还原，本页统一表述为
 * 「尚未填报」（partial 时显示已填 x/y 行），不做无依据的猜测。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import StickyBar from '@/components/StickyBar.vue'
import AppendSuppliersPanel from './AppendSuppliersPanel.vue'
import { closeRfq, exportRfq, getRfq, getRfqProgress } from '@/api/rfq'
import { useBreakpoint } from '@/composables/useBreakpoint'
import {
  formatDateTime,
  formatDateTimeShort,
  formatRemaining,
  secondsUntil,
} from '@/composables/useFormat'

import {
  appendErrorInfo,
  appendRfqSuppliers,
  copyText,
  listSupplierOptions,
  safePush,
} from './support'

defineOptions({ name: 'RfqProgress' })

const route = useRoute()
const router = useRouter()
const { isMobile } = useBreakpoint()

const rfqId = ref(Number(route.params.id) || 0)
const detail = ref(null)
const assignees = ref([])
// 无权访问（数据隔离：他人创建的单据）
const denied = ref(false)
const supplierOptions = ref([])
const loading = ref(false)
const busy = ref(false)

/** 「追加供货商」弹层（task-11：已发布未截止可追加受邀供货商） */
const appendState = reactive({
  visible: false,
  busy: false,
  supplier_ids: [],
})

const columns = [
  { prop: 'supplier_name', label: '供货商', minWidth: 150, slot: 'supplier_name' },
  { prop: 'contact', label: '联系人 / 电话', width: 168, slot: 'contact' },
  { prop: 'status', label: '报价状态', width: 122, slot: 'status' },
  { prop: 'progress', label: '填写进度', width: 176, slot: 'progress' },
  { prop: 'last_saved_at', label: '最后保存时间', width: 156, slot: 'last_saved_at' },
  { prop: 'ops', label: '操作', width: 122, slot: 'ops' },
]

const pendingList = computed(() => assignees.value.filter((a) => a.status === 'pending'))
const partialList = computed(() => assignees.value.filter((a) => a.status === 'partial'))
const quotedList = computed(() => assignees.value.filter((a) => a.status === 'quoted'))
/** 「未报价」= 尚未提交（pending + partial），催办对象 */
const unquotedList = computed(() => [...pendingList.value, ...partialList.value])
const quotedCount = computed(() => quotedList.value.length)

const remainingText = computed(() => {
  if (!detail.value?.deadline) return '—'
  if (detail.value.status === 'closed') return '已截止'
  const left = secondsUntil(detail.value.deadline)
  if (left === null || left <= 0) return '已截止'
  return formatRemaining(left)
})

const remainingTone = computed(() => {
  if (!detail.value?.deadline || detail.value.status === 'closed') return 'is-plain'
  const left = secondsUntil(detail.value.deadline)
  if (left === null || left <= 0) return 'is-plain'
  return left <= 24 * 3600 ? 'is-danger' : 'is-warn'
})

const headSub = computed(() => {
  const d = detail.value
  if (!d) return ''
  return `${d.rfq_no} · ${d.project || '—'} · ${d.lines?.length ?? 0} 行明细 · 截止 ${formatDateTime(d.deadline)}`
})

// ---------------------------------------------------------------------------
// 取数
// ---------------------------------------------------------------------------
async function load() {
  if (!rfqId.value) return
  loading.value = true
  denied.value = false
  try {
    const [detailData, progressData] = await Promise.all([
      getRfq(rfqId.value),
      getRfqProgress(rfqId.value).catch(() => null),
    ])
    detail.value = detailData
    const list = Array.isArray(progressData)
      ? progressData
      : Array.isArray(detailData?.assignees)
        ? detailData.assignees
        : []
    // 未报价置顶（催办视图），同组内按名称
    assignees.value = [...list].sort((a, b) => {
      const rank = { pending: 0, partial: 1, quoted: 2 }
      const diff = (rank[a.status] ?? 9) - (rank[b.status] ?? 9)
      if (diff !== 0) return diff
      return String(a.supplier_name).localeCompare(String(b.supplier_name), 'zh-CN')
    })
  } catch (error) {
    // 数据隔离：非管理员访问他人单据会拿到 40300。
    // 此前这里是静默 catch，页面会停留在空态并显示"暂无受邀供货商"，
    // 容易被误解成"单据存在但没有供货商"，因此单独标记出来给出明确提示。
    if (error?.code === 40300 || error?.forbidden || error?.status === 403) {
      denied.value = true
      detail.value = null
      assignees.value = []
    }
    // 其余错误 request.js 已统一 Toast
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// 追加供货商（task-11）
// ---------------------------------------------------------------------------
/**
 * 候选 = 启用的供货商档案 − 已被分派的供货商。
 * 差集用 assignees[].supplier_id（RfqDetail 已带）与 /meta/suppliers 档案列表计算。
 */
const appendableSuppliers = computed(() => {
  const assigned = new Set(assignees.value.map((a) => Number(a.supplier_id)))
  return supplierOptions.value.filter(
    (s) => Number(s.status) !== 0 && !assigned.has(Number(s.id)),
  )
})

async function loadSupplierOptions() {
  try {
    const list = await listSupplierOptions()
    supplierOptions.value = Array.isArray(list) ? list : []
  } catch {
    supplierOptions.value = []
  }
}

function openAppend() {
  if (!canAppendSuppliers.value) {
    ElMessage.warning('仅「已发布且未截止」的询价单可以追加供货商')
    return
  }
  appendState.supplier_ids = []
  appendState.visible = true
}

async function onConfirmAppend() {
  if (!appendState.supplier_ids.length) {
    ElMessage.warning('请至少选择一家供货商')
    return
  }
  appendState.busy = true
  try {
    // 用后端信封里的 message 原样提示（含"跳过 N 家"这类只有后端知道的信息）
    const res = await appendRfqSuppliers(rfqId.value, appendState.supplier_ids)
    if (res?.data && typeof res.data === 'object') detail.value = res.data
    appendState.visible = false
    ElMessage.success(res?.message || '已追加供货商')
    await load()
  } catch (error) {
    await handleAppendError(error)
  } finally {
    appendState.busy = false
  }
}

/** 失败按 code 分支：40900 显示后端原文；40301 提示已截止并刷新为只读 */
async function handleAppendError(error) {
  const info = appendErrorInfo(error)
  if (info.kind === 'closed') {
    appendState.visible = false
    ElMessage.warning(info.message)
    await load()
    return
  }
  if (info.kind === 'conflict') {
    // 后端原文，例如「没有新增供货商：鑫达办公」
    await ElMessageBox.alert(info.message, '无法追加供货商', {
      type: 'warning',
      confirmButtonText: '知道了',
    }).catch(() => {})
    await load() // 可能是他人刚追加过 → 刷新候选与列表
    return
  }
  if (info.kind === 'forbidden') {
    ElMessage.error(info.message)
    return
  }
  if (info.kind === 'missing') {
    await ElMessageBox.alert(
      '后端未找到「追加供货商」接口：\nPOST /api/rfqs/{id}/append-suppliers\n请确认已部署最新后端后重试。',
      '接口未就绪',
      { type: 'warning', confirmButtonText: '知道了' },
    ).catch(() => {})
    return
  }
  ElMessage.error(info.message)
}

// ---------------------------------------------------------------------------
// 展示辅助
// ---------------------------------------------------------------------------
function percent(row) {
  const total = Number(row?.line_count || 0)
  if (!total) return 0
  return Math.min(100, Math.round((Number(row?.quoted_line_count || 0) / total) * 100))
}

function progressTone(row) {
  if (row.status === 'quoted') return 'is-ok'
  if (row.status === 'partial') return 'is-warn'
  return ''
}

function fillText(row) {
  if (row.status === 'pending') return '尚未填报'
  return `${row.quoted_line_count}/${row.line_count} 行`
}

function lastSavedText(row) {
  if (row.status === 'quoted' && row.submitted_at) {
    return `提交于 ${formatDateTimeShort(row.submitted_at)}`
  }
  if (row.last_saved_at) return `保存于 ${formatDateTimeShort(row.last_saved_at)}`
  return '—'
}

/** 状态徽标：pending 在催办语境下显示为「未报价」（危险色） */
function badgeLabel(row) {
  if (row.status === 'pending') return '未报价'
  return ''
}

function toneOf(row) {
  if (row.status === 'pending') return 'danger'
  return ''
}

// ---------------------------------------------------------------------------
// 复制催办名单（Q10 定稿：替代本期不做的通知功能）
// ---------------------------------------------------------------------------
function contactLine(row) {
  const parts = [row.contact_name || '联系人未登记', row.contact_phone || '电话未登记']
  return `${row.supplier_name}（${parts.join(' ')}）`
}

function buildUnquotedText() {
  const head = `【询价催办】${detail.value?.title || ''}（${detail.value?.rfq_no || ''}）`
  const tail = detail.value?.deadline
    ? `截止时间：${formatDateTime(detail.value.deadline)}（剩余 ${remainingText.value}）`
    : '截止时间：未设置'
  const rows = unquotedList.value.map((row, index) => {
    const progress = row.status === 'partial' ? `，已填 ${row.quoted_line_count}/${row.line_count} 行` : ''
    return `${index + 1}. ${contactLine(row)}${progress}`
  })
  return [head, tail, `未报价 ${unquotedList.value.length} 家：`, ...rows].join('\n')
}

async function onCopyUnquoted() {
  if (!unquotedList.value.length) {
    ElMessage.info('当前没有未报价的供货商')
    return
  }
  const ok = await copyText(buildUnquotedText())
  if (ok) ElMessage.success(`已复制 ${unquotedList.value.length} 家未报价供货商的名单与联系方式`)
  else ElMessage.warning('复制失败，请手动选择文本复制')
}

async function onCopyContact(row) {
  const text = `${row.supplier_name} ${row.contact_name || ''} ${row.contact_phone || ''}`.trim()
  const ok = await copyText(text)
  if (ok) ElMessage.success('联系方式已复制')
  else ElMessage.warning('复制失败，请手动复制')
}

// ---------------------------------------------------------------------------
// 页头操作
// ---------------------------------------------------------------------------
function goReport() {
  safePush(router, `/purchase/report?rfq_id=${rfqId.value}&view=comparison`)
}

async function onExport() {
  busy.value = true
  try {
    await exportRfq(rfqId.value)
    ElMessage.success('导出已开始')
  } catch {
    /* request.js 已统一 Toast */
  } finally {
    busy.value = false
  }
}

async function onClose() {
  const confirmed = await ElMessageBox.confirm(
    `还有 ${unquotedList.value.length} 家供货商未提交报价。\n提前截止后供货商将无法再保存或提交，已提交的报价保留。此操作不可撤销。`,
    '提前截止？',
    { type: 'warning', confirmButtonText: '确认截止', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return
  busy.value = true
  try {
    await closeRfq(rfqId.value, {})
    ElMessage.success('已截止')
    await load()
  } catch {
    /* request.js 已统一 Toast */
  } finally {
    busy.value = false
  }
}

/** 已发布且**未过截止时间** → 可追加受邀供货商（task-11）；草稿/已截止都不显示入口 */
const canAppendSuppliers = computed(
  () => detail.value?.status === 'published' && (secondsUntil(detail.value?.deadline) ?? -1) > 0,
)

onMounted(async () => {
  await Promise.all([load(), loadSupplierOptions()])
  // 从报价单列表「追加供货商」跳转过来时自动打开（/purchase/rfq/:id?append=1）
  if (route.query.append && canAppendSuppliers.value) openAppend()
})
</script>

<template>
  <div class="rfq-progress">
    <!-- 数据隔离：非管理员访问他人创建的单据会收到 40300。
         明确告知"无权访问"而不是显示空态，避免误以为单据没有受邀供货商。 -->
    <div v-if="denied" class="denied-card">
      <h2 class="denied-card__title">无权访问该询价单</h2>
      <p class="denied-card__desc">
        该单据由其他人员创建，当前账号（我方账号）只能查看和操作自己发出的询价单。
        如需协作，请联系管理员或由单据创建人操作。
      </p>
      <el-button type="primary" @click="router.push('/purchase/rfq')">返回报价单列表</el-button>
    </div>
    <template v-else>
    <header class="page-head">
      <div class="page-head__main">
        <h2 class="page-head__title">
          {{ detail?.title || '报价进度' }}
          <StatusBadge v-if="detail" :status="detail.status" size="small" />
        </h2>
        <p class="page-head__sub">
          <span class="num">{{ headSub }}</span>
          <span v-if="detail?.status === 'published'" :class="remainingTone" class="page-head__remain">
            （剩余 {{ remainingText }}）
          </span>
        </p>
      </div>
      <div class="page-head__actions">
        <el-button v-if="canAppendSuppliers" @click="openAppend">追加供货商</el-button>
        <el-button :loading="busy" @click="onExport">导出报价结果</el-button>
        <el-button @click="goReport">查看统计报表</el-button>
        <el-button
          v-if="detail?.status === 'published'"
          type="primary"
          :loading="busy"
          @click="onClose"
        >
          提前截止
        </el-button>
      </div>
    </header>

    <!-- 页头信息卡（手机端完整可用） -->
    <section v-if="isMobile" class="m-card">
      <b class="m-card__ttl">{{ detail?.title }}</b>
      <div class="m-card__sub num">{{ detail?.rfq_no }}</div>
      <dl class="dl">
        <dt>状态</dt>
        <dd><StatusBadge v-if="detail" :status="detail.status" size="small" /></dd>
        <dt>截止时间</dt>
        <dd class="num">{{ formatDateTime(detail?.deadline) }}</dd>
        <dt>剩余</dt>
        <dd :class="remainingTone">{{ remainingText }}</dd>
        <dt>受邀 / 已报价</dt>
        <dd class="num">{{ assignees.length }} 家 / {{ quotedCount }} 家</dd>
      </dl>
    </section>

    <!-- 未报价警示条（FR-RFQ-14） -->
    <div v-if="unquotedList.length" class="alert alert--warn">
      <span class="alert__i">!</span>
      <div class="alert__body">
        <div>
          <b>还有 {{ unquotedList.length }} 家供货商未报价。</b>
          系统不发送通知，请线下催办。
          <button type="button" class="alert__link" @click="onCopyUnquoted">
            复制未报价名单
          </button>
        </div>
        <div class="alert__names">
          <span v-for="row in unquotedList" :key="row.supplier_id">
            {{ row.supplier_name
            }}<template v-if="row.status === 'partial'">
              （报价中 {{ row.quoted_line_count }}/{{ row.line_count }} 行）</template
            >
          </span>
        </div>
      </div>
    </div>
    <div v-else-if="assignees.length" class="alert alert--ok">
      <span class="alert__i">✓</span>
      <div>全部 {{ assignees.length }} 家受邀供货商均已提交报价。</div>
    </div>

    <!-- 手机端：一键复制（催办主操作，44px 热区） -->
    <el-button
      v-if="isMobile"
      class="copy-all"
      :disabled="!unquotedList.length"
      @click="onCopyUnquoted"
    >
      复制未报价名单与联系方式
    </el-button>

    <!-- ================= 桌面：分派与报价状态表 ================= -->
    <template v-if="!isMobile">
      <DataTable
        :data="assignees"
        :columns="columns"
        row-key="supplier_id"
        :loading="loading"
        empty-text="该询价单暂无受邀供货商。请回到单据编辑页勾选受邀供货商后重新发布。"
      >
        <template #supplier_name="{ row }">
          <span class="name">{{ row.supplier_name }}</span>
        </template>

        <template #contact="{ row }">
          <div>{{ row.contact_name || '—' }}</div>
          <div class="sub num">{{ row.contact_phone || '未登记电话' }}</div>
        </template>

        <template #status="{ row }">
          <StatusBadge
            :status="row.status"
            :label="badgeLabel(row)"
            :tone="toneOf(row)"
            size="small"
          />
        </template>

        <template #progress="{ row }">
          <div v-if="row.status === 'pending'" class="sub">尚未填报</div>
          <div v-else class="prog">
            <div class="prog__bar" :class="progressTone(row)">
              <i :style="{ width: `${percent(row)}%` }" />
            </div>
            <span class="prog__txt num">{{ fillText(row) }}</span>
          </div>
        </template>

        <template #last_saved_at="{ row }">
          <span class="num sub">{{ lastSavedText(row) }}</span>
        </template>

        <template #ops="{ row }">
          <el-button
            v-if="row.status !== 'pending'"
            link
            type="primary"
            @click="goReport"
          >
            查看报价
          </el-button>
          <el-button v-else link type="primary" @click="onCopyContact(row)">
            复制联系方式
          </el-button>
        </template>
      </DataTable>

      <div class="summary">
        <span>
          已报价 <b class="num">{{ quotedCount }}</b> 家 · 报价中
          <b class="num">{{ partialList.length }}</b> 家 · 未报价
          <b class="num">{{ pendingList.length }}</b> 家
        </span>
        <span class="summary__right">已报价家数按「提交报价」计</span>
      </div>
    </template>

    <!-- ================= 手机：分组卡片（催办主场景） ================= -->
    <template v-else>
      <section v-if="unquotedList.length" class="group">
        <h3 class="group__title">未报价（{{ unquotedList.length }}）</h3>
        <article v-for="row in unquotedList" :key="row.supplier_id" class="m-card m-card--row">
          <div class="m-card__top">
            <b class="m-card__ttl">{{ row.supplier_name }}</b>
            <StatusBadge status="pending" label="未报价" tone="danger" size="small" />
          </div>
          <div class="m-card__meta">
            {{ row.contact_name || '联系人未登记' }} ·
            <span class="num">{{ row.contact_phone || '电话未登记' }}</span> ·
            {{ row.status === 'partial' ? fillText(row) : '尚未填报' }}
          </div>
          <div class="m-card__ops">
            <button type="button" class="linkbtn" @click="onCopyContact(row)">复制联系方式</button>
            <button type="button" class="linkbtn" @click="goReport">查看明细</button>
          </div>
        </article>
      </section>

      <section v-if="quotedList.length || partialList.length" class="group">
        <h3 class="group__title">
          已报价 / 报价中（{{ quotedList.length + partialList.length }}）
        </h3>
        <article
          v-for="row in [...partialList, ...quotedList]"
          :key="row.supplier_id"
          class="m-card m-card--row"
        >
          <div class="m-card__top">
            <b class="m-card__ttl">{{ row.supplier_name }}</b>
            <StatusBadge :status="row.status" size="small" />
          </div>
          <div class="m-card__meta">
            {{ row.contact_name || '—' }} · {{ lastSavedText(row) }}
          </div>
          <div class="prog prog--solo">
            <div class="prog__bar" :class="progressTone(row)">
              <i :style="{ width: `${percent(row)}%` }" />
            </div>
            <span class="prog__txt num">{{ fillText(row) }}</span>
          </div>
        </article>
      </section>

      <el-empty
        v-if="!assignees.length && !loading"
        description="该询价单暂无可催办的供货商，请先发布单据"
        :image-size="72"
      />
    </template>

    <!-- 手机端吸底操作栏 -->
    <StickyBar v-if="isMobile" class="rfq-progress__sticky">
      <span>未报价 <b class="num">{{ unquotedList.length }} 家</b></span>
      <template #actions>
        <el-button v-if="canAppendSuppliers" @click="openAppend">追加供货商</el-button>
        <el-button :loading="busy" @click="onExport">导出</el-button>
        <el-button
          v-if="detail?.status === 'published'"
          type="primary"
          :loading="busy"
          @click="onClose"
        >
          提前截止
        </el-button>
      </template>
    </StickyBar>

    <!-- ============ 追加供货商：桌面用弹窗 ============ -->
    <el-dialog
      v-if="!isMobile"
      v-model="appendState.visible"
      title="追加供货商"
      width="560px"
      :close-on-click-modal="false"
    >
      <AppendSuppliersPanel
        v-model="appendState.supplier_ids"
        :options="appendableSuppliers"
        :invited-count="assignees.length"
        :deadline="detail?.deadline"
        :busy="appendState.busy"
      />
      <template #footer>
        <div class="append-actions">
          <el-button :disabled="appendState.busy" @click="appendState.visible = false">
            取消
          </el-button>
          <el-button
            type="primary"
            :loading="appendState.busy"
            :disabled="!appendState.supplier_ids.length"
            @click="onConfirmAppend"
          >
            确认追加
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ============ 追加供货商：手机用底部弹层（PRD 10.4） ============ -->
    <el-drawer
      v-else
      v-model="appendState.visible"
      title="追加供货商"
      direction="btt"
      size="88%"
      :lock-scroll="false"
    >
      <AppendSuppliersPanel
        v-model="appendState.supplier_ids"
        :options="appendableSuppliers"
        :invited-count="assignees.length"
        :deadline="detail?.deadline"
        :busy="appendState.busy"
      />
      <template #footer>
        <div class="append-actions append-actions--sheet">
          <el-button :disabled="appendState.busy" @click="appendState.visible = false">
            取消
          </el-button>
          <el-button
            type="primary"
            :loading="appendState.busy"
            :disabled="!appendState.supplier_ids.length"
            @click="onConfirmAppend"
          >
            确认追加
          </el-button>
        </div>
      </template>
    </el-drawer>
    </template>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.rfq-progress {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
}

// —— 无权访问（数据隔离）——
.denied-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: v.$sp-3;
  padding: v.$sp-5;
  background: v.$surface;
  border: 1px solid v.$line;
  border-left: 3px solid v.$danger;
  border-radius: v.$r-md;
}

.denied-card__title {
  margin: 0;
  font-size: v.$fs-lg;
  font-weight: 600;
  color: v.$danger;
}

.denied-card__desc {
  margin: 0;
  font-size: v.$fs-sm;
  line-height: 1.7;
  color: v.$ink-500;
}

// —— 页头 ——
.page-head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
  flex-wrap: wrap;
}

.page-head__main {
  min-width: 0;
}

.page-head__title {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
  font-size: v.$fs-title;
  letter-spacing: -0.015em;
}

.page-head__sub {
  margin-top: 3px;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.page-head__remain {
  font-weight: 600;

  &.is-warn {
    color: v.$warn;
  }

  &.is-danger {
    color: v.$danger;
  }
}

.page-head__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

// —— 提示条 ——
.alert {
  display: flex;
  gap: v.$sp-2;
  align-items: flex-start;
  padding: 11px 13px;
  border: 1px solid;
  border-radius: v.$r-md;
  font-size: v.$fs-sm;

  &--warn {
    background: v.$warn-bg;
    border-color: v.$warn-line;
    color: #7a4208;
  }

  &--ok {
    background: v.$ok-bg;
    border-color: v.$ok-line;
    color: #0b5c3b;
  }
}

.alert__i {
  flex: none;
  font-weight: 800;
  line-height: 1.3;
}

.alert__body {
  min-width: 0;
}

.alert__link {
  min-height: v.$touch-target;
  padding: 0 v.$sp-2;
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$brand-700;
  background: transparent;
  border: 0;
  text-decoration: underline;
  cursor: pointer;
}

.alert__names {
  margin-top: 5px;
  color: #7a4208;
  word-break: break-all;

  span + span::before {
    content: '、';
  }
}

// —— 表格单元格 ——
.name {
  font-weight: 600;
}

.sub {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

// —— 进度条 ——
.prog {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  min-width: 118px;
}

.prog--solo {
  margin-top: v.$sp-2;
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

// —— 底部汇总（设计稿 tfoot）——
.summary {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: 10px v.$sp-4;
  margin-top: v.$sp-2;
  font-size: v.$fs-sm;
  color: v.$ink-500;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
}

.summary__right {
  margin-left: auto;
  color: v.$ink-400;
}

// —— 手机端 ——
.copy-all {
  width: 100%;
  min-height: v.$touch-target;
  margin-left: 0 !important;
}

.group {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
}

.group__title {
  margin: 2px 0 0 2px;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-400;
}

.m-card {
  padding: 11px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;

  &--row {
    margin-bottom: 0;
  }
}

.m-card__ttl {
  font-size: v.$fs-sm;
}

.m-card__top {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
}

.m-card__meta {
  margin-top: 5px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.m-card__sub {
  margin-top: 4px;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.m-card__ops {
  display: flex;
  gap: v.$sp-4;
  margin-top: v.$sp-2;
  padding-top: v.$sp-2;
  border-top: 1px dashed v.$line;
}

.linkbtn {
  min-height: v.$touch-target;
  padding: 0;
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$brand-700;
  background: transparent;
  border: 0;
  cursor: pointer;
}

// —— 追加供货商弹层底部按钮（FR-RWD-06：热区 ≥44px）——
.append-actions {
  display: flex;
  justify-content: flex-end;
  gap: v.$sp-2;
}

.append-actions--sheet {
  flex-direction: column-reverse; // 手机端：主操作在上、取消在下易达位（PRD 10.4）

  :deep(.el-button) {
    width: 100%;
    min-height: v.$touch-target;
    margin-left: 0;
  }
}

.dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px v.$sp-3;
  margin-top: v.$sp-3;
  font-size: v.$fs-xs;

  dt {
    color: v.$ink-400;
  }

  dd {
    margin: 0;
    font-weight: 600;
    text-align: right;

    &.is-warn {
      color: v.$warn;
    }

    &.is-danger {
      color: v.$danger;
    }
  }
}

@include bp.mobile {
  .rfq-progress {
    padding-bottom: calc(v.$bottom-bar-h + 24px);
  }

  .denied-card {
    padding: v.$sp-4;

    // FR-RWD-06：移动端可点击元素 ≥44px
    :deep(.el-button) {
      width: 100%;
      min-height: v.$touch-target;
    }
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
