<script setup>
/**
 * RfqEdit.vue — 新建 / 编辑询价单（设计稿 02-2）
 * ---------------------------------------------------------------------------
 * 路由：/purchase/rfq/new（新建）、/purchase/rfq/:id/edit（编辑草稿，
 *       已发布单据在此页只读并只提供「撤回为草稿」）
 *
 * PRD：FR-RFQ-07~12、FR-IMP-01~08、FR-RWD-12 / 10.2
 *
 * 关键实现说明（与后端契约对齐，均已 curl 实测）：
 *  1. 明细行 payload 字段：seq / material_name / spec / unit / project / quantity(字符串) / remark
 *     （schemas.RfqLineIn；quantity 用字符串透传，避免 JS 浮点误差）
 *  2. **草稿允许不完整明细**（PRD FR-RFQ-09 / TC-09）：后端 RfqLineIn 已放宽为
 *     material_name / unit 可为空、quantity 可为 null（quantity 非空时仍要求 > 0），
 *     所以本页保存草稿时**只丢弃完全空白行**，部分填写的行原样落库；
 *     发布前的必填校验在前端与后端各做一次，逐条列出错误行号并阻断（FR-RFQ-10）。
 *  3. Excel 预校验接口 POST /rfqs/import/preview 需要 rfq_id 查询参数且目标必须是本人草稿，
 *     所以导入前会先静默落一次草稿（见 support.js 的 previewRfqImport）。
 *  4. 后端 publish 返回的 message 形如「发布校验未通过：\n第2行 材料名称：必填」，
 *     本页按行拆开原样逐条展示。
 *  5. 可选查询参数一律经 support.js 的 compactParams 剔除空值（空串会被后端 date 解析拒绝）。
 *  6. 截止时间用原生 datetime-local（PRD 10.4：移动端优先原生日期时间控件，
 *     避免小屏弹出超宽桌面面板）；值格式 YYYY-MM-DDTHH:mm，提交时补 :00。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

import StatusBadge from '@/components/StatusBadge.vue'
import StickyBar from '@/components/StickyBar.vue'
import {
  confirmImport,
  createRfq,
  downloadImportTemplate,
  getRfq,
  listRfqs,
  publishRfq,
  updateRfq,
  withdrawRfq,
} from '@/api/rfq'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatDateTime, secondsUntil, toDateTimeInputValue } from '@/composables/useFormat'

import AppendSuppliersPanel from './AppendSuppliersPanel.vue'
import {
  appendErrorInfo,
  appendRfqSuppliers,
  listSupplierOptions,
  listUnits,
  previewRfqImport,
  safePush,
} from './support'

defineOptions({ name: 'RfqEdit' })

/** 明细列顺序（Excel 横向粘贴按此顺序对齐） */
const LINE_FIELDS = ['material_name', 'spec', 'unit', 'project', 'quantity', 'remark']

const route = useRoute()
const router = useRouter()
const { isMobile } = useBreakpoint()

let keySeq = 0
function newKey() {
  keySeq += 1
  return `ln-${keySeq}`
}

const rfqId = ref(route.params.id ? Number(route.params.id) : null)
const detail = ref(null)
const loading = ref(true)
// 无权访问（数据隔离：他人创建的单据）
const denied = ref(false)
const saving = ref(false)
const publishing = ref(false)
const withdrawing = ref(false)
const lines = ref([])
const units = ref([])
const suppliers = ref([])
const projectOptions = ref([])
/** 逐条错误：{ scope:'header'|'row', row?, field, text } */
const errors = ref([])
/** Excel 横向粘贴的起始单元格 */
const activeCell = ref(null)
const importInputRef = ref(null)

const form = reactive({
  title: '',
  project: '',
  deadline: '',
  remark: '',
  internal_remark: '',
  supplier_ids: [],
})

const importState = reactive({
  visible: false,
  file: null,
  busy: false,
  progress: 0,
  result: null,
  mode: 'append',
  addUnknownUnits: false,
})

/** 「追加供货商」弹窗（新增需求：已发布且未截止可追加受邀供货商） */
const appendState = reactive({
  visible: false,
  busy: false,
  supplier_ids: [],
})

// ---------------------------------------------------------------------------
// 计算属性
// ---------------------------------------------------------------------------
const status = computed(() => detail.value?.status || 'draft')
/** 已发布 / 已截止：禁止增删改明细（FR-RFQ-12） */
const locked = computed(() => Boolean(detail.value) && detail.value.status !== 'draft')
const isCreate = computed(() => !rfqId.value)
/** 已发布且未截止 → 允许追加供货商（明细仍锁定） */
const canAppendSuppliers = computed(
  () => detail.value?.status === 'published' && (secondsUntil(detail.value?.deadline) ?? -1) > 0,
)
/** 尚未受邀、可追加的启用供货商档案 */
const appendableSuppliers = computed(() => {
  const invited = new Set(form.supplier_ids.map(Number))
  return suppliers.value.filter((s) => Number(s.status) !== 0 && !invited.has(Number(s.id)))
})
const pageTitle = computed(() => {
  if (isCreate.value) return '新建报价单'
  return locked.value ? '询价单详情' : '编辑报价单'
})
const pageSub = computed(() => {
  if (!locked.value) return '草稿可随时保存；发布后明细将锁定，供货商开始填报。'
  if (canAppendSuppliers.value) {
    return '该单据已发布，明细已锁定；截止前可「追加供货商」继续邀请报价。如需改明细请先「撤回为草稿」（会作废已有报价）。'
  }
  return '该单据已截止，明细与受邀供货商均已锁定；如需修改请先「撤回为草稿」（会作废已有报价）。'
})
const filledCount = computed(
  () => lines.value.filter((line) => isRowComplete(line)).length,
)
const unitOptions = computed(() => {
  const names = units.value.map((u) => u.name)
  const used = lines.value.map((l) => l.unit).filter(Boolean)
  return [...new Set([...names, ...used])]
})
const errorCellSet = computed(
  () => new Set(errors.value.filter((e) => e.scope === 'row').map((e) => `${e.row}:${e.field}`)),
)
const errorRowSet = computed(
  () => new Set(errors.value.filter((e) => e.scope === 'row').map((e) => e.row)),
)
const rowErrorSummary = computed(() => errors.value.filter((e) => e.scope === 'row'))

// ---------------------------------------------------------------------------
// 行级工具
// ---------------------------------------------------------------------------
function emptyLine() {
  return {
    key: newKey(),
    line_uid: null,
    material_name: '',
    spec: '',
    unit: '',
    project: form.project || '',
    quantity: '',
    remark: '',
  }
}

function isRowEmpty(line) {
  return LINE_FIELDS.every((field) => !String(line[field] ?? '').trim())
}

function isRowComplete(line) {
  const qty = Number(line.quantity)
  return (
    Boolean(String(line.material_name || '').trim()) &&
    Boolean(String(line.unit || '').trim()) &&
    String(line.quantity ?? '').trim() !== '' &&
    Number.isFinite(qty) &&
    qty > 0
  )
}

/** '40.000' → '40'（后端 Decimal 三位小数，编辑框里去掉无意义尾零） */
function trimQty(value) {
  const text = String(value ?? '').trim()
  if (!text.includes('.')) return text
  return text.replace(/\.?0+$/, '')
}

function addLine(index) {
  if (locked.value) return
  const at = typeof index === 'number' ? index + 1 : lines.value.length
  lines.value.splice(at, 0, emptyLine())
}

function removeLine(index) {
  if (locked.value) return
  lines.value.splice(index, 1)
  if (!lines.value.length) lines.value.push(emptyLine())
  errors.value = []
}

function copyLine(index) {
  if (locked.value) return
  const source = lines.value[index]
  lines.value.splice(index + 1, 0, { ...source, key: newKey(), line_uid: null })
}

function moveLine(index, delta) {
  if (locked.value) return
  const target = index + delta
  if (target < 0 || target >= lines.value.length) return
  const list = lines.value
  const swap = list[index]
  list[index] = list[target]
  list[target] = swap
}

function onCellFocus(rowIndex, field) {
  activeCell.value = { rowIndex, field }
}

// ---------------------------------------------------------------------------
// 从 Excel 粘贴多行（FR-RFQ-07）
// ---------------------------------------------------------------------------
function normalizeCell(field, raw) {
  const text = String(raw ?? '').trim()
  if (field === 'quantity') {
    const cleaned = text.replace(/[￥¥,\s]/g, '')
    return Number.isFinite(Number(cleaned)) ? cleaned : ''
  }
  return text
}

function onPaste(event) {
  if (locked.value) return
  const text = event.clipboardData?.getData('text/plain') || ''
  if (!text) return
  // 单值粘贴交给浏览器默认行为；含制表符/换行才视为「从 Excel 复制多行」
  if (!/[\t\n]/.test(text)) return
  event.preventDefault()

  const matrix = text
    .replace(/\r\n?/g, '\n')
    .replace(/\n+$/, '')
    .split('\n')
    .map((row) => row.split('\t'))

  const startRow = activeCell.value?.rowIndex ?? lines.value.length
  const startCol = Math.max(
    0,
    activeCell.value ? LINE_FIELDS.indexOf(activeCell.value.field) : 0,
  )

  let cells = 0
  matrix.forEach((rowCells, rowOffset) => {
    const index = startRow + rowOffset
    while (lines.value.length <= index) lines.value.push(emptyLine())
    rowCells.forEach((raw, colOffset) => {
      const field = LINE_FIELDS[startCol + colOffset]
      if (!field) return
      const value = normalizeCell(field, raw)
      if (value === '') return
      lines.value[index][field] = value
      cells += 1
    })
    if (!lines.value[index].project && form.project) {
      lines.value[index].project = form.project
    }
  })

  errors.value = []
  ElMessage.success(`已粘贴 ${matrix.length} 行 / ${cells} 个单元格`)
}

// ---------------------------------------------------------------------------
// 校验（FR-RFQ-10：逐条列出错误行号并阻断）
// ---------------------------------------------------------------------------
function collectErrors({ forPublish = true } = {}) {
  const list = []
  if (!form.title.trim()) {
    list.push({ scope: 'header', field: 'title', text: '表头「单据名称」不能为空' })
  }
  if (!form.project.trim()) {
    list.push({ scope: 'header', field: 'project', text: '表头「项目」不能为空' })
  }

  if (forPublish) {
    if (!form.deadline) {
      list.push({ scope: 'header', field: 'deadline', text: '表头「报价截止时间」不能为空' })
    } else {
      const left = secondsUntil(form.deadline)
      if (left === null || left <= 0) {
        list.push({
          scope: 'header',
          field: 'deadline',
          text: '表头「报价截止时间」必须晚于当前时间',
        })
      }
    }

    if (!form.supplier_ids.length) {
      list.push({ scope: 'header', field: 'supplier_ids', text: '表头「受邀供货商」至少选择 1 家' })
    }

    const kept = lines.value.filter((line) => !isRowEmpty(line))
    if (!kept.length) {
      list.push({ scope: 'header', field: 'lines', text: '明细：至少需要 1 行明细' })
    }

    lines.value.forEach((line, index) => {
      if (isRowEmpty(line)) return
      const no = index + 1
      if (!String(line.material_name || '').trim()) {
        list.push({ scope: 'row', row: no, field: 'material_name', text: `第 ${no} 行「材料名称」未填写` })
      }
      if (!String(line.unit || '').trim()) {
        list.push({ scope: 'row', row: no, field: 'unit', text: `第 ${no} 行「单位」未选择` })
      } else if (units.value.length && !units.value.some((u) => u.name === line.unit)) {
        list.push({
          scope: 'row',
          row: no,
          field: 'unit',
          text: `第 ${no} 行「单位」不在计量单位字典内（${line.unit}）`,
        })
      }
      const qty = Number(line.quantity)
      if (!String(line.quantity ?? '').trim() || !Number.isFinite(qty) || qty <= 0) {
        list.push({
          scope: 'row',
          row: no,
          field: 'quantity',
          text: `第 ${no} 行「采购数量」必须为大于 0 的数字`,
        })
      }
    })
  }

  return list
}

function errorText(rowNo, field) {
  const found = errors.value.find((e) => e.scope === 'row' && e.row === rowNo && e.field === field)
  return found ? found.text : ''
}

function headerError(field) {
  const found = errors.value.find((e) => e.scope === 'header' && e.field === field)
  return found ? found.text : ''
}

async function showErrors(title, list) {
  if (!list?.length) return
  await ElMessageBox.alert(list.map((e) => `· ${e.text}`).join('\n'), title, {
    type: 'warning',
    confirmButtonText: '知道了',
  }).catch(() => {})
}

/** 后端的逐条错误（\n 分隔）原样呈现 */
async function showApiError(error) {
  const rows = String(error?.message || '操作失败')
    .split('\n')
    .map((t) => t.trim())
    .filter(Boolean)
  if (rows.length > 1) {
    await ElMessageBox.alert(rows.slice(1).map((t) => `· ${t}`).join('\n'), rows[0], {
      type: 'warning',
      confirmButtonText: '知道了',
    }).catch(() => {})
  }
}

// ---------------------------------------------------------------------------
// 保存 / 发布 / 撤回
// ---------------------------------------------------------------------------
function buildPayload(rowList) {
  return {
    title: form.title.trim(),
    project: form.project.trim(),
    // 原生 datetime-local → 'YYYY-MM-DDTHH:mm'，补秒后交给后端解析
    deadline: form.deadline ? `${form.deadline}${form.deadline.length === 16 ? ':00' : ''}` : null,
    remark: form.remark.trim() || null,
    internal_remark: form.internal_remark.trim() || null,
    supplier_ids: [...form.supplier_ids],
    lines: rowList.map((line, index) => ({
      seq: index + 1,
      material_name: String(line.material_name || '').trim(),
      spec: String(line.spec || '').trim() || null,
      unit: String(line.unit || '').trim(),
      project: String(line.project || '').trim() || form.project.trim() || null,
      quantity:
        String(line.quantity ?? '').trim() === '' ||
        !Number.isFinite(Number(String(line.quantity).trim())) ||
        Number(String(line.quantity).trim()) <= 0
          ? null
          : String(line.quantity).trim(),
      remark: String(line.remark || '').trim() || null,
    })),
  }
}

/**
 * 落一次草稿。
 * ---------------------------------------------------------------------------
 * 只丢弃**完全空白行**（材料名称/规格/单位/项目/数量/备注全空），避免用户误点
 * 「添加行」在库里留下垃圾行；部分填写的行原样保存。
 * 后端已按 PRD FR-RFQ-09 / TC-09 放宽：material_name / unit 可为空、quantity 可为 null
 * （quantity 非空时仍要求 > 0，所以 0 / 负数 / 非数字一律按「未填」下发 null，
 * 由发布校验逐条报出"第 N 行 采购数量：必须大于 0"，避免整单保存被 400 卡死）。
 *
 * @returns {Promise<number|null>} 单据 ID
 */
async function persistDraft() {
  const kept = lines.value.filter((line) => !isRowEmpty(line))
  const body = buildPayload(kept)
  const data = rfqId.value ? await updateRfq(rfqId.value, body) : await createRfq(body)
  const id = Number(data?.id ?? data?.rfq_id ?? rfqId.value) || null
  if (id) {
    rfqId.value = id
    if (data && typeof data === 'object') detail.value = data
  }
  return id
}

async function onSaveDraft() {
  // 草稿只校验表头（title/project 是 schema 必填）；明细不完整不再阻断（PRD FR-RFQ-09）
  const headerErrors = collectErrors({ forPublish: false })
  errors.value = headerErrors
  if (headerErrors.length) {
    await showErrors('保存失败：请先补全表头必填项', headerErrors)
    return
  }
  saving.value = true
  try {
    const created = !rfqId.value
    const id = await persistDraft()
    if (!id) return
    ElMessage.success(created ? '草稿已保存' : '草稿已更新')
    if (created) {
      // 新建成功后切到编辑路由，便于刷新与分享链接
      const moved = await safePush(router, `/purchase/rfq/${id}/edit`)
      if (!moved) {
        ElMessage.info(`草稿已保存（单号 ID ${id}），当前路由未声明编辑页，可直接在列表页打开`)
        await load()
      }
    }
  } catch (error) {
    await showApiError(error)
  } finally {
    saving.value = false
  }
}

async function onPublish() {
  const list = collectErrors({ forPublish: true })
  errors.value = list
  if (list.length) {
    await showErrors('发布校验未通过，已阻断发布', list)
    return
  }

  const confirmed = await ElMessageBox.confirm(
    `发布后将为 ${form.supplier_ids.length} 家受邀供货商各生成一份独立报价单，供货商只能看到自己那一份与本说明；明细行将锁定不可修改。`,
    '发布并通知供货商？',
    { type: 'info', confirmButtonText: '发布', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!confirmed) return

  publishing.value = true
  try {
    const id = await persistDraft()
    if (!id) return
    const data = await publishRfq(id, {})
    if (data && typeof data === 'object') detail.value = data
    ElMessage.success(`发布成功：已为 ${form.supplier_ids.length} 家供货商生成报价单`)
    await load()
  } catch (error) {
    await showApiError(error)
  } finally {
    publishing.value = false
  }
}

/**
 * 追加供货商（新增需求：已发布且未截止可追加）
 * ---------------------------------------------------------------------------
 * 只新增受邀供货商，不动明细行、不清空已有报价；新受邀家在截止前可正常填报。
 * 接口与错误码见 support.js 的 appendRfqSuppliers / appendErrorInfo（task-11）。
 */
function openAppend() {
  if (!canAppendSuppliers.value) {
    ElMessage.warning('仅「已发布且未截止」的询价单可以追加供货商；已截止的请先撤回为草稿')
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
    // 原样使用后端信封的 message（含"跳过 N 家"这类只有后端知道的信息）
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
    await ElMessageBox.alert(info.message, '无法追加供货商', {
      type: 'warning',
      confirmButtonText: '知道了',
    }).catch(() => {})
    await load()
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

/** 撤回为草稿：二次确认 + 作废已有报价提示（FR-RFQ-12） */
async function onWithdraw() {
  const quoted = (detail.value?.assignees || []).filter((a) => Number(a.quoted_line_count) > 0)
  const quotedTip = quoted.length
    ? `\n注意：${quoted.map((a) => a.supplier_name).join('、')} 已提交过报价，撤回将作废这些报价（保留历史快照，可追溯）。`
    : ''
  const confirmed = await ElMessageBox.confirm(
    `撤回后单据回到「草稿」，明细可修改，已生成的供货商报价单全部作废。${quotedTip}\n此操作不可撤销。`,
    '撤回为草稿？',
    {
      type: 'warning',
      confirmButtonText: '确认撤回',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    },
  ).catch(() => false)
  if (!confirmed) return

  withdrawing.value = true
  try {
    await withdrawRfq(rfqId.value, {})
    ElMessage.success('已撤回为草稿，可继续修改明细')
    await load()
  } catch (error) {
    await showApiError(error)
  } finally {
    withdrawing.value = false
  }
}

// ---------------------------------------------------------------------------
// Excel 导入（FR-IMP-01~08）
// ---------------------------------------------------------------------------
async function onDownloadTemplate() {
  try {
    await downloadImportTemplate()
    ElMessage.success('模板已开始下载')
  } catch (error) {
    await showApiError(error)
  }
}

function openImport() {
  if (locked.value) return
  if (isMobile.value) {
    ElMessage.warning('Excel 导入仅桌面端提供，建议使用电脑操作')
    return
  }
  importState.visible = true
  importState.file = null
  importState.result = null
  importState.progress = 0
  importState.mode = 'append'
  importState.addUnknownUnits = false
}

function triggerImportFile() {
  importInputRef.value?.click()
}

async function onImportFileChange(event) {
  const file = event.target?.files?.[0]
  if (event.target) event.target.value = ''
  if (!file) return
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    ElMessage.error('仅支持 .xlsx / .xls 文件')
    return
  }
  importState.file = file
  await runPreview()
}

async function runPreview() {
  if (!importState.file) return
  importState.busy = true
  importState.progress = 0
  try {
    // 预校验接口要求 rfq_id 指向本人可编辑的草稿：先把表头与完整明细落库
    const headerErrors = collectErrors({ forPublish: false })
    if (headerErrors.length) {
      errors.value = headerErrors
      await showErrors('导入前请先补全表头必填项', headerErrors)
      return
    }
    const id = await persistDraft()
    if (!id) return
    importState.result = await previewRfqImport(id, importState.file, (percent) => {
      importState.progress = percent
    })
  } catch (error) {
    await showApiError(error)
  } finally {
    importState.busy = false
  }
}

async function onConfirmImport() {
  const token = importState.result?.token
  if (!token) {
    ElMessage.error('预校验结果已失效，请重新选择文件')
    return
  }
  importState.busy = true
  try {
    const result = await confirmImport({
      token,
      mode: importState.mode,
      add_unknown_units: importState.addUnknownUnits,
    })
    const imported = Number(result?.imported_rows ?? 0)
    const skipped = Number(result?.skipped_rows ?? 0)
    ElMessage.success(
      `已导入 ${imported} 行${skipped ? `，跳过 ${skipped} 行（单位不在字典内）` : ''}`,
    )
    importState.visible = false
    await load()
  } catch (error) {
    await showApiError(error)
  } finally {
    importState.busy = false
  }
}

// ---------------------------------------------------------------------------
// 取数
// ---------------------------------------------------------------------------
function applyDetail(data) {
  detail.value = data
  form.title = data?.title || ''
  form.project = data?.project || ''
  form.deadline = toDateTimeInputValue(data?.deadline)
  form.remark = data?.remark || ''
  form.internal_remark = data?.internal_remark || ''
  form.supplier_ids = (data?.assignees || [])
    .filter((a) => Number(a.line_count) > 0)
    .map((a) => a.supplier_id)

  const list = [...(data?.lines || [])].sort((a, b) => Number(a.seq) - Number(b.seq))
  lines.value = list.length
    ? list.map((line) => ({
        key: newKey(),
        line_uid: line.line_uid,
        material_name: line.material_name || '',
        spec: line.spec || '',
        unit: line.unit || '',
        project: line.project || '',
        quantity: trimQty(line.quantity),
        remark: line.remark || '',
      }))
    : [emptyLine()]
  errors.value = []
}

async function load() {
  loading.value = true
  denied.value = false
  try {
    if (rfqId.value) {
      const data = await getRfq(rfqId.value)
      rfqId.value = Number(data?.id ?? rfqId.value)
      applyDetail(data)
    } else {
      detail.value = null
      lines.value = [emptyLine()]
      errors.value = []
    }
  } catch (error) {
    // 数据隔离：非管理员打开他人单据会拿到 40300。
    // 不标记出来的话，页面会显示成一张空表单，看起来像"新建"，容易误导。
    if (error?.code === 40300 || error?.forbidden || error?.status === 403) {
      denied.value = true
      detail.value = null
    }
    // 其余错误 request.js 统一 Toast；不覆盖用户已录入内容
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const [unitList, supplierList] = await Promise.all([
      listUnits(),
      listSupplierOptions(),
    ])
    units.value = Array.isArray(unitList) ? unitList : []
    suppliers.value = Array.isArray(supplierList) ? supplierList : []
  } catch {
    units.value = []
    suppliers.value = []
  }
}

/** 项目字段的历史值联想（PRD 5.1.2：自由输入 + 历史值联想，不建字典） */
async function loadProjectOptions() {
  try {
    const data = await listRfqs({ page: 1, page_size: 200 })
    projectOptions.value = [
      ...new Set((data?.items || []).map((item) => item.project).filter(Boolean)),
    ]
  } catch {
    projectOptions.value = []
  }
}

function queryProjects(query, callback) {
  const keyword = String(query || '').trim()
  const result = projectOptions.value
    .filter((project) => !keyword || project.includes(keyword))
    .slice(0, 12)
    .map((project) => ({ value: project }))
  callback(result)
}

// 行级项目默认继承表头项目
watch(
  () => form.project,
  (value, oldValue) => {
    lines.value.forEach((line) => {
      if (!line.project || line.project === oldValue) line.project = value
    })
  },
)

watch(
  () => form.title,
  () => {
    if (errors.value.length) errors.value = []
  },
)

onMounted(async () => {
  await Promise.all([loadMeta(), loadProjectOptions()])
  await load()
  // 从列表/进度页「追加供货商」跳转过来时自动打开弹窗（?append=1）
  if (route.query.append && canAppendSuppliers.value) openAppend()
})
</script>

<template>
  <div class="rfq-edit">
    <!-- 数据隔离：非管理员打开他人创建的单据会收到 40300，明确提示而不是显示空表单 -->
    <div v-if="denied" class="denied-card">
      <h2 class="denied-card__title">无权访问该询价单</h2>
      <p class="denied-card__desc">
        该单据由其他人员创建，当前账号只能查看和编辑自己发出的询价单。
        如需协作，请联系管理员或由单据创建人操作。
      </p>
      <el-button type="primary" @click="router.push('/purchase/rfq')">返回报价单列表</el-button>
    </div>
    <template v-else>
    <header class="page-head">
      <div class="page-head__main">
        <h2 class="page-head__title">
          {{ pageTitle }}
          <span v-if="detail" class="num page-head__no">{{ detail.rfq_no }}</span>
          <StatusBadge v-if="detail" :status="status" size="small" />
        </h2>
        <p class="page-head__sub">{{ pageSub }}</p>
      </div>
      <div class="page-head__actions">
        <template v-if="!locked">
          <el-button :loading="saving" @click="onSaveDraft">保存草稿</el-button>
          <el-button type="primary" :loading="publishing" @click="onPublish">
            发布并通知供货商
          </el-button>
        </template>
        <template v-else>
          <el-button v-if="canAppendSuppliers" type="primary" @click="openAppend">
            追加供货商
          </el-button>
          <el-button :loading="withdrawing" type="danger" plain @click="onWithdraw">
            撤回为草稿
          </el-button>
        </template>
      </div>
    </header>

    <!-- 已发布：只读说明（未截止时可追加供货商） -->
    <div v-if="locked" class="alert alert--info">
      <span class="alert__i">i</span>
      <div>
        单据已于
        <b class="num">{{ formatDateTime(detail?.published_at || detail?.created_at) }}</b>
        发布，明细行已锁定（防止供货商填价后行结构变化导致数据错位）。
        <template v-if="canAppendSuppliers">
          截止前可<b>追加受邀供货商</b>（不影响明细与已有报价）；若必须改明细，请使用「撤回为草稿」，
          撤回会<b>作废该单已有报价</b>（保留历史快照）。
        </template>
        <template v-else>
          单据已截止，不能再追加供货商。若必须修改，请使用「撤回为草稿」，
          撤回会<b>作废该单已有报价</b>（保留历史快照）。
        </template>
      </div>
    </div>

    <!-- 手机端：能力边界提示（FR-RWD-12/14）
         用 CSS 媒体查询控制显隐（而不是只靠 JS 断点），保证任何情况下
         窄屏都会看到这句提示，不会出现"入口藏了但用户不知道为什么"。 -->
    <div v-if="!locked" class="alert alert--warn rfq-edit__mobile-hint">
      <span class="alert__i">!</span>
      <div>
        <b>建议在电脑上创建询价单。</b>手机端支持填写与保存，但
        <b>Excel 导入、批量粘贴</b>等功能仅桌面端提供。
      </div>
    </div>

    <!-- 逐条错误清单（FR-RFQ-10） -->
    <div v-if="errors.length" class="alert alert--danger">
      <span class="alert__i">!</span>
      <div>
        <b>有 {{ errors.length }} 项问题需要处理，已阻断发布：</b>
        <ul class="err-list">
          <li v-for="(item, index) in errors" :key="`${item.field}-${item.row || 0}-${index}`">
            {{ item.text }}
          </li>
        </ul>
      </div>
    </div>

    <!-- ================= 表头 ================= -->
    <section class="card">
      <div class="card__head">
        <b>单据信息</b>
        <span class="card__sub">带 * 的为发布必填项</span>
      </div>
      <div class="card__body head-grid">
        <label class="fld">
          <span class="fld__label">单据名称 <i>*</i></span>
          <el-input
            v-model="form.title"
            maxlength="100"
            show-word-limit
            placeholder="如：办公用品-10月补货询价"
            :disabled="locked"
            :class="{ 'is-invalid': headerError('title') }"
          />
          <span v-if="headerError('title')" class="fld__err">{{ headerError('title') }}</span>
        </label>

        <label class="fld">
          <span class="fld__label">项目 <i>*</i></span>
          <el-autocomplete
            v-model="form.project"
            :fetch-suggestions="queryProjects"
            placeholder="如：办公用品"
            :disabled="locked"
            style="width: 100%"
            :class="{ 'is-invalid': headerError('project') }"
          />
          <span v-if="headerError('project')" class="fld__err">{{ headerError('project') }}</span>
        </label>

        <label class="fld">
          <span class="fld__label">报价截止时间 <i>*</i></span>
          <input
            v-model="form.deadline"
            class="native-input"
            type="datetime-local"
            :disabled="locked"
            :class="{ 'is-invalid': headerError('deadline') }"
          />
          <span v-if="headerError('deadline')" class="fld__err">{{ headerError('deadline') }}</span>
        </label>

        <label class="fld fld--span2">
          <span class="fld__label">
            受邀供货商 <i>*</i>
            <em class="fld__hint">已选 {{ form.supplier_ids.length }} 家</em>
          </span>
          <el-select
            v-model="form.supplier_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="搜索并选择至少 1 家供货商"
            :disabled="locked"
            style="width: 100%"
            :class="{ 'is-invalid': headerError('supplier_ids') }"
          >
            <el-option
              v-for="supplier in suppliers"
              :key="supplier.id"
              :label="supplier.name"
              :value="supplier.id"
              :disabled="supplier.status === 0"
            >
              <span>{{ supplier.name }}</span>
              <span class="opt-sub">
                {{ supplier.contact_name || '—' }} · {{ supplier.contact_phone || '—' }}
              </span>
            </el-option>
          </el-select>
          <span v-if="headerError('supplier_ids')" class="fld__err">
            {{ headerError('supplier_ids') }}
          </span>
        </label>

        <label class="fld fld--wide">
          <span class="fld__label">
            对供货商可见的备注
            <em class="fld__hint">供货商在填报页可见</em>
          </span>          <el-input
            v-model="form.remark"
            maxlength="500"
            placeholder="如：付款方式、交货地点、是否含运费"
            :disabled="locked"
          />
        </label>

        <label class="fld fld--span3">
          <span class="fld__label">
            内部备注
            <em class="fld__hint">仅我方可见，供货商不可见</em>
          </span>
          <el-input
            v-model="form.internal_remark"
            maxlength="500"
            placeholder="如：优先考虑本地供货商"
            :disabled="locked"
          />
        </label>
      </div>
    </section>

    <!-- ================= 明细 ================= -->
    <section class="card">
      <div class="card__head">
        <b>询价明细</b>
        <span class="card__sub">共 {{ lines.length }} 行 · 序号自动生成</span>
        <div class="card__tools">
          <!-- FR-RWD-12：Excel 导入 / 批量粘贴仅桌面端提供。
               这里用 CSS 媒体查询兜底隐藏（不用 v-if），
               避免 JS 断点判断失效时窄屏仍然露出导入入口。 -->
          <div v-if="!locked && !isMobile" class="card__tools-import">
            <el-button size="small" @click="onDownloadTemplate">下载导入模板</el-button>
            <el-button size="small" @click="openImport">Excel 导入</el-button>
          </div>
          <el-button v-if="!locked" size="small" class="card__tools-add" @click="addLine()">
            + 添加行
          </el-button>
        </div>
      </div>

      <!-- 桌面：粘贴提示 + 可编辑表格 -->
      <div v-if="!isMobile" class="lines">
        <div v-if="!locked" class="alert alert--info alert--inner">
          <span class="alert__i">i</span>
          <div>
            可直接从 Excel <b>复制多行</b>粘贴到表格；粘贴时按列顺序
            （材料名称 / 规格型号 / 单位 / 项目 / 采购数量 / 行备注）自动对齐，
            起点为当前选中的单元格。
          </div>
        </div>

        <div class="lines__scroll" @paste="onPaste">
          <el-table :data="lines" row-key="key" size="small" border max-height="560">
            <el-table-column type="index" label="序号" width="56" align="center" />
            <el-table-column label="材料名称 *" width="182">
              <template #default="{ row, $index }">
                <el-input
                  v-model="row.material_name"
                  size="small"
                  maxlength="100"
                  placeholder="必填"
                  :disabled="locked"
                  :class="{ 'is-invalid': errorCellSet.has(`${$index + 1}:material_name`) }"
                  @focus="onCellFocus($index, 'material_name')"
                />
                <div v-if="errorText($index + 1, 'material_name')" class="cell-err">
                  {{ errorText($index + 1, 'material_name') }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="规格型号" width="170">
              <template #default="{ row, $index }">
                <el-input
                  v-model="row.spec"
                  size="small"
                  maxlength="200"
                  placeholder="—"
                  :disabled="locked"
                  @focus="onCellFocus($index, 'spec')"
                />
              </template>
            </el-table-column>
            <el-table-column label="单位 *" width="112">
              <template #default="{ row, $index }">
                <el-select
                  v-model="row.unit"
                  size="small"
                  filterable
                  placeholder="必选"
                  :disabled="locked"
                  style="width: 100%"
                  :class="{ 'is-invalid': errorCellSet.has(`${$index + 1}:unit`) }"
                  @focus="onCellFocus($index, 'unit')"
                >
                  <el-option v-for="name in unitOptions" :key="name" :label="name" :value="name" />
                </el-select>
                <div v-if="errorText($index + 1, 'unit')" class="cell-err">
                  {{ errorText($index + 1, 'unit') }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="项目" width="140">
              <template #default="{ row, $index }">
                <el-input
                  v-model="row.project"
                  size="small"
                  maxlength="100"
                  :disabled="locked"
                  @focus="onCellFocus($index, 'project')"
                />
              </template>
            </el-table-column>
            <el-table-column label="采购数量 *" width="118">
              <template #default="{ row, $index }">
                <el-input
                  v-model="row.quantity"
                  size="small"
                  inputmode="decimal"
                  class="qty-input"
                  placeholder=">0"
                  :disabled="locked"
                  :class="{ 'is-invalid': errorCellSet.has(`${$index + 1}:quantity`) }"
                  @focus="onCellFocus($index, 'quantity')"
                />
                <div v-if="errorText($index + 1, 'quantity')" class="cell-err">
                  {{ errorText($index + 1, 'quantity') }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="行备注" min-width="150">
              <template #default="{ row, $index }">
                <el-input
                  v-model="row.remark"
                  size="small"
                  maxlength="200"
                  placeholder="—"
                  :disabled="locked"
                  @focus="onCellFocus($index, 'remark')"
                />
              </template>
            </el-table-column>
            <el-table-column v-if="!locked" label="操作" width="168" align="center">
              <template #default="{ $index }">
                <div class="rowops">
                  <button type="button" title="上移" @click="moveLine($index, -1)">↑</button>
                  <button type="button" title="下移" @click="moveLine($index, 1)">↓</button>
                  <button type="button" title="复制行" @click="copyLine($index)">复制</button>
                  <button type="button" class="is-danger" title="删除行" @click="removeLine($index)">
                    删
                  </button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="lines__foot">
          <span v-if="rowErrorSummary.length" class="lines__foot-err">
            {{ rowErrorSummary[0].text }}，发布前需补齐
          </span>
          <span v-else class="lines__foot-ok">
            草稿会原样保存所有已填内容（只丢弃完全空白行）；发布前会逐条校验必填项并列出问题行号。
          </span>
          <span class="num lines__foot-count">
            已填 {{ filledCount }} / {{ lines.length }} 行
          </span>
        </div>
      </div>

      <!-- 手机：明细卡片（设计稿 02-2 手机形态；FR-RWD-12） -->
      <div v-else class="lines-mobile">
        <article
          v-for="(row, index) in lines"
          :key="row.key"
          class="m-card"
          :class="{ 'is-error': errorRowSet.has(index + 1) }"
        >
          <header class="m-card__head">
            <span class="num m-card__no">{{ String(index + 1).padStart(2, '0') }}</span>
            <b class="m-card__ttl">{{ row.material_name || '材料名称未填写' }}</b>
            <button v-if="!locked" type="button" class="m-card__del" @click="removeLine(index)">
              删除
            </button>
          </header>
          <div class="m-card__body">
            <label class="fld">
              <span class="fld__label">材料名称 <i>*</i></span>
              <el-input
                v-model="row.material_name"
                placeholder="必填"
                maxlength="100"
                :disabled="locked"
              />
            </label>
            <div class="m-grid">
              <label class="fld">
                <span class="fld__label">规格型号</span>
                <el-input v-model="row.spec" maxlength="200" :disabled="locked" />
              </label>
              <label class="fld">
                <span class="fld__label">单位 <i>*</i></span>
                <el-select
                  v-model="row.unit"
                  filterable
                  placeholder="必选"
                  :disabled="locked"
                  style="width: 100%"
                >
                  <el-option v-for="name in unitOptions" :key="name" :label="name" :value="name" />
                </el-select>
              </label>
            </div>
            <div class="m-grid">
              <label class="fld">
                <span class="fld__label">项目</span>
                <el-input v-model="row.project" maxlength="100" :disabled="locked" />
              </label>
              <label class="fld">
                <span class="fld__label">采购数量 <i>*</i></span>
                <el-input
                  v-model="row.quantity"
                  inputmode="decimal"
                  class="qty-input"
                  placeholder=">0"
                  :disabled="locked"
                />
              </label>
            </div>
            <label class="fld">
              <span class="fld__label">行备注</span>
              <el-input v-model="row.remark" maxlength="200" :disabled="locked" />
            </label>
          </div>
          <!-- 校验失败：整卡变红并直接说明缺什么，用户不必逐行找红框 -->
          <div v-if="errorRowSet.has(index + 1)" class="m-card__err">
            <span
              v-for="item in rowErrorSummary.filter((item) => item.row === index + 1)"
              :key="item.field"
            >
              {{ item.text }}
            </span>
          </div>
          <div v-else-if="isRowComplete(row)" class="m-card__ok">已填写完整</div>
        </article>

        <el-button v-if="!locked" class="lines-mobile__add" @click="addLine()">
          + 添加一行明细
        </el-button>
      </div>
    </section>

    <!-- 发布说明（设计稿底部品牌色卡片） -->
    <section v-if="!locked" class="publish-note">
      <div class="publish-note__text">
        <b>发布后会发生什么：</b>
        为 {{ form.supplier_ids.length }} 家受邀供货商各生成一份独立报价单；供货商只能看到自己的那一份与本说明；明细行将锁定不可修改。
      </div>
      <div class="publish-note__actions">
        <el-button :loading="saving" @click="onSaveDraft">保存草稿</el-button>
        <el-button type="primary" :loading="publishing" @click="onPublish">发布</el-button>
      </div>
    </section>

    <!-- 手机端吸底操作栏（FR-RWD-19） -->
    <StickyBar v-if="isMobile" class="rfq-edit__sticky">
      <span v-if="!locked">已填 <b class="num">{{ filledCount }}/{{ lines.length }}</b> 行</span>
      <span v-else>受邀 <b class="num">{{ form.supplier_ids.length }}</b> 家</span>
      <template #actions>
        <template v-if="!locked">
          <el-button :loading="saving" @click="onSaveDraft">保存草稿</el-button>
          <el-button type="primary" :loading="publishing" @click="onPublish">发布</el-button>
        </template>
        <template v-else>
          <el-button v-if="canAppendSuppliers" type="primary" @click="openAppend">
            追加供货商
          </el-button>
          <el-button type="danger" plain @click="onWithdraw">撤回</el-button>
        </template>
      </template>
    </StickyBar>

    <!-- ============ 追加供货商：桌面弹窗 / 手机底部弹层（task-11） ============ -->
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
        :invited-count="form.supplier_ids.length"
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
        :invited-count="form.supplier_ids.length"
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

    <!-- ================= Excel 导入弹窗（桌面） ================= -->
    <el-dialog
      v-model="importState.visible"
      title="Excel 导入明细"
      width="820px"
      :close-on-click-modal="false"
    >
      <div class="import">
        <div class="import__step">
          <span class="import__badge">1</span>
          <div class="import__body">
            <b>选择文件</b>
            <p class="import__hint">
              列顺序：序号 / 材料名称 / 规格型号 / 单位 / 项目 / 采购数量（与导入模板一致）。
              支持 .xlsx 与 .xls，单次上限 2000 行。
            </p>
            <div class="import__row">
              <el-button size="small" @click="onDownloadTemplate">下载导入模板</el-button>
              <el-button size="small" type="primary" :disabled="importState.busy" @click="triggerImportFile">
                选择 Excel 文件
              </el-button>
              <span v-if="importState.file" class="import__file">
                {{ importState.file.name }}
                <em v-if="importState.busy" class="num">{{ importState.progress }}%</em>
              </span>
              <input
                ref="importInputRef"
                class="import__input"
                type="file"
                accept=".xlsx,.xls"
                @change="onImportFileChange"
              />
            </div>
          </div>
        </div>

        <div class="import__step">
          <span class="import__badge">2</span>
          <div class="import__body">
            <b>预校验结果</b>
            <p v-if="!importState.result" class="import__hint">上传文件后在此展示预览与错误清单。</p>
            <template v-else>
              <div class="import__stats">
                <span>共 <b class="num">{{ importState.result.total_rows }}</b> 行</span>
                <span class="is-ok">有效 <b class="num">{{ importState.result.valid_rows }}</b> 行</span>
                <span :class="{ 'is-danger': importState.result.error_rows > 0 }">
                  错误 <b class="num">{{ importState.result.error_rows }}</b> 行
                </span>
                <span v-if="importState.result.unknown_units?.length" class="is-warn">
                  字典外单位：{{ importState.result.unknown_units.join('、') }}
                </span>
              </div>

              <div v-if="importState.result.errors?.length" class="import__errors">
                <b>错误清单（精确到行列）</b>
                <el-table :data="importState.result.errors" size="small" max-height="200" border>
                  <el-table-column prop="row" label="行号" width="72" align="center" />
                  <el-table-column prop="column" label="列" width="110" />
                  <el-table-column prop="value" label="值" width="140" show-overflow-tooltip />
                  <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
                </el-table>
              </div>
              <div v-else class="import__allok">✓ 全部校验通过，可确认导入</div>

              <div v-if="importState.result.preview?.length" class="import__preview">
                <b>导入预览（前 {{ importState.result.preview.length }} 行）</b>
                <el-table :data="importState.result.preview" size="small" max-height="220" border>
                  <el-table-column prop="seq" label="序号" width="60" align="center" />
                  <el-table-column prop="material_name" label="材料名称" min-width="130" />
                  <el-table-column prop="spec" label="规格型号" min-width="120" show-overflow-tooltip />
                  <el-table-column prop="unit" label="单位" width="70" />
                  <el-table-column prop="project" label="项目" min-width="100" />
                  <el-table-column prop="quantity" label="采购数量" width="100" align="right" />
                </el-table>
              </div>
            </template>
          </div>
        </div>

        <div class="import__step">
          <span class="import__badge">3</span>
          <div class="import__body">
            <b>导入策略</b>
            <div class="import__mode">
              <el-radio-group v-model="importState.mode">
                <el-radio value="append">追加到现有明细</el-radio>
                <el-radio value="replace">清空后导入</el-radio>
              </el-radio-group>
              <el-checkbox v-model="importState.addUnknownUnits">
                自动把字典外单位加入计量单位字典
              </el-checkbox>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="import__footer">
          <el-button @click="importState.visible = false">关闭</el-button>
          <el-button
            type="primary"
            :loading="importState.busy"
            :disabled="!importState.result || !importState.result.token"
            @click="onConfirmImport"
          >
            确认导入 {{ importState.result?.valid_rows ?? 0 }} 行
          </el-button>
        </div>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.rfq-edit {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
}

// —— 页头 ——
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

.page-head__no {
  font-size: v.$fs-xs;
  font-weight: 500;
  color: v.$ink-400;
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

// —— 提示条 ——
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

  &--warn {
    background: v.$warn-bg;
    border-color: v.$warn-line;
    color: #7a4208;
  }

  &--danger {
    background: v.$danger-bg;
    border-color: v.$danger-line;
    color: #8e1b12;
  }

  &--inner {
    margin: v.$sp-3 v.$sp-4 0;
  }
}

.alert__i {
  flex: none;
  font-weight: 800;
  line-height: 1.3;
}

.err-list {
  margin-top: v.$sp-1;
  padding-left: v.$sp-4;
  list-style: disc;

  li {
    margin: 2px 0;
  }
}

// —— 卡片 ——
.card {
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  overflow: hidden;
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
  gap: v.$sp-2;
  flex-wrap: wrap;
}

.card__body {
  padding: v.$sp-4;
}

// —— 表单字段 ——
.head-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: v.$sp-4;
}

.fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;

  // 表头三列网格：受邀供货商占 2 列，内部备注整行
  &--span2 {
    grid-column: span 2;
  }

  &--span3 {
    grid-column: span 3;
  }
}

.fld__label {
  display: flex;
  align-items: center;
  gap: v.$sp-1;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-500;

  i {
    color: v.$danger;
    font-style: normal;
  }
}

.fld__hint {
  font-weight: 400;
  font-style: normal;
  color: v.$ink-400;
}

.fld__err {
  font-size: v.$fs-xs;
  color: v.$danger;
}

.native-input {
  width: 100%;
  height: 32px;
  padding: 0 11px;
  font-size: v.$fs-sm;
  font-family: inherit;
  color: v.$ink-900;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;

  &:focus {
    outline: none;
    border-color: v.$brand-600;
    box-shadow: 0 0 0 3px v.$brand-100;
  }

  &:disabled {
    background: v.$surface-sunken;
    color: v.$ink-500;
  }

  &.is-invalid {
    border-color: v.$danger-line;
    background: v.$danger-bg;
  }
}

.opt-sub {
  float: right;
  margin-left: v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

// —— 明细表格 ——
.lines__scroll {
  padding: 0 v.$sp-4;
  overflow-x: auto;
}

.qty-input :deep(.el-input__inner) {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

:deep(.el-input.is-invalid .el-input__wrapper),
:deep(.el-select.is-invalid .el-input__wrapper) {
  background: v.$danger-bg;
  box-shadow: 0 0 0 1px v.$danger-line inset;
}

.cell-err {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.35;
  color: v.$danger;
}

.rowops {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: v.$sp-2;

  button {
    min-width: 26px;
    height: 26px;
    padding: 0 6px;
    font-size: v.$fs-xs;
    color: v.$ink-700;
    background: v.$surface;
    border: 1px solid v.$line-strong;
    border-radius: v.$r-sm;
    cursor: pointer;

    &:hover {
      border-color: v.$brand-600;
      color: v.$brand-700;
    }

    &.is-danger {
      color: v.$danger;
      border-color: v.$danger-line;
    }
  }
}

.lines__foot {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: v.$sp-3 v.$sp-4;
  border-top: 1px solid v.$line;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.lines__foot-err {
  color: v.$danger;
  font-weight: 600;
}

.lines__foot-count {
  margin-left: auto;
}

// —— 发布说明 ——
.publish-note {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: 13px v.$sp-4;
  background: v.$brand-50;
  border: 1px solid v.$brand-100;
  border-radius: v.$r-lg;
  // 窄屏兜底：文字与按钮区必须能换行，否则会撑出横向滚动（FR-RWD-01）
  flex-wrap: wrap;
}

.publish-note__text {
  flex: 1 1 320px;
  min-width: 0;
  font-size: v.$fs-sm;
  color: v.$brand-800;
}

.publish-note__actions {
  margin-left: auto;
  display: flex;
  gap: v.$sp-2;
  flex: none;
  flex-wrap: wrap;
}

// 明细卡片头部的工具区（导入入口默认显示，手机端由下方媒体查询隐藏）
.card__tools-import {
  display: flex;
  gap: v.$sp-2;
}

// 手机端能力边界提示：默认隐藏，<768px 才显示（不依赖 JS 断点）
.rfq-edit__mobile-hint {
  display: none;
}

// —— 手机明细卡片 ——
.lines-mobile {
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
  padding: v.$sp-3;
}

.m-card {
  padding: 10px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;

  &.is-error {
    border-color: v.$danger-line;
    background: v.$danger-bg;
  }
}

.m-card__head {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-bottom: v.$sp-2;
}

.m-card__no {
  font-size: 11px;
  color: v.$ink-400;
}

.m-card__ttl {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-sm;
  word-break: break-word;
}

.m-card.is-error .m-card__ttl {
  color: v.$danger;
}

.m-card__del {
  flex: none;
  min-width: v.$touch-target;
  min-height: v.$touch-target;
  padding: 0 v.$sp-2;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$danger;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.m-card__body {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
}

.m-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: v.$sp-2;
}

.m-card__err {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: v.$sp-2;
  font-size: v.$fs-xs;
  color: v.$danger;
}

.m-card__ok {
  margin-top: v.$sp-2;
  font-size: v.$fs-xs;
  color: v.$ok;
}

.lines-mobile__add {
  width: 100%;
  min-height: v.$touch-target;
  margin-left: 0 !important;
}

// —— 导入弹窗 ——
.import {
  display: flex;
  flex-direction: column;
  gap: v.$sp-4;
}

.import__step {
  display: flex;
  gap: v.$sp-3;
}

.import__badge {
  flex: none;
  width: 22px;
  height: 22px;
  font-size: v.$fs-xs;
  font-weight: 700;
  line-height: 22px;
  color: #fff;
  text-align: center;
  background: v.$brand-700;
  border-radius: 50%;
}

.import__body {
  flex: 1;
  min-width: 0;
}

.import__hint {
  margin-top: 3px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.import__row {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-top: v.$sp-2;
  flex-wrap: wrap;
}

.import__file {
  font-size: v.$fs-xs;
  color: v.$ink-700;
}

.import__input {
  display: none;
}

.import__stats {
  display: flex;
  gap: v.$sp-4;
  margin-top: v.$sp-2;
  font-size: v.$fs-sm;
  flex-wrap: wrap;

  .is-ok {
    color: v.$ok;
  }

  .is-danger {
    color: v.$danger;
  }

  .is-warn {
    color: v.$warn;
  }
}

.import__errors,
.import__preview {
  margin-top: v.$sp-3;

  b {
    display: block;
    margin-bottom: v.$sp-1;
    font-size: v.$fs-sm;
  }
}

.import__allok {
  margin-top: v.$sp-2;
  font-size: v.$fs-sm;
  color: v.$ok;
}

.import__mode {
  display: flex;
  align-items: center;
  gap: v.$sp-5;
  margin-top: v.$sp-2;
  flex-wrap: wrap;
}

.import__footer {
  display: flex;
  justify-content: flex-end;
  gap: v.$sp-2;
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

// —— 响应式 ——
@include bp.mobile {
  .denied-card {
    padding: v.$sp-4;

    // FR-RWD-06：移动端可点击元素 ≥44px
    :deep(.el-button) {
      width: 100%;
      min-height: v.$touch-target;
    }
  }
  .rfq-edit {
    padding-bottom: calc(v.$bottom-bar-h + 74px);
  }

  .head-grid {
    grid-template-columns: 1fr;
  }

  .fld--span2,
  .fld--span3 {
    grid-column: span 1;
  }

  .page-head__actions {
    width: 100%;

    :deep(.el-button) {
      flex: 1;
      min-height: v.$touch-target;
    }
  }

  .native-input {
    height: 38px;
    font-size: v.$fs-input-mobile;
  }

  .card__body {
    padding: v.$sp-3;
  }

  // FR-RWD-01：发布说明在窄屏纵向排布，绝不横向溢出
  .publish-note {
    align-items: flex-start;
    flex-direction: column;
  }

  .publish-note__text {
    flex: 1 1 auto;
    width: 100%;
  }

  .publish-note__actions {
    margin-left: 0;
    width: 100%;

    :deep(.el-button) {
      flex: 1;
      min-height: v.$touch-target;
    }
  }

  // FR-RWD-12：Excel 导入 / 批量粘贴入口在手机端隐藏（CSS 兜底，不依赖 JS 断点）
  .card__tools-import {
    display: none !important;
  }

  // 手机端能力边界提示
  .rfq-edit__mobile-hint {
    display: flex;
  }

  // FR-RWD-06：所有可点元素热区 ≥44×44（视觉尺寸不变，用 padding 扩大点击区）
  .card__tools {
    gap: v.$sp-2;

    :deep(.el-button) {
      min-height: v.$touch-target;
      margin-left: 0;
    }
  }

  .card__tools-add {
    flex: 1;
  }

  // 桌面表格里的行操作按钮（正常情况下手机端不渲染；万一渲染也要满足热区）
  .rowops {
    gap: v.$sp-1;

    button {
      min-width: v.$touch-target;
      min-height: v.$touch-target;
    }
  }
}

@include bp.tablet {
  .head-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .fld--span2,
  .fld--span3 {
    grid-column: span 2;
  }
}
</style>
