/**
 * 供货商报价填报 —— 纯数据逻辑层（无 Vue、无 DOM，可被 node 直接 import 单测）
 * ---------------------------------------------------------------------------
 * 契约来源（已用 curl 对 http://127.0.0.1:8000 实测，并与 /openapi.json 交叉核对；
 * 路径占位符沿用后端真实参数名 rfq_id）：
 *   GET  /api/supplier/rfqs                 → { items: SupplierRfqListItem[], meta }
 *   GET  /api/supplier/rfqs/{rfq_id}        → SupplierRfqDetail
 *   PUT  /api/supplier/rfqs/{rfq_id}/quotes → QuoteSaveRequest（body.submit 控制保存/提交）
 *   POST /api/supplier/rfqs/{rfq_id}/submit → 便捷别名【该路由已存在，openapi 可查】：
 *                                             复用同一保存逻辑并强制 submit=True
 *                                             （body 里传 submit:false 也会被忽略）
 *   POST /api/supplier/attachments          → { filename, original_name, size, url }
 *
 * 关键结论（务必保留）：
 *  1. 保存与提交共用同一套后端逻辑：PUT 用 body.submit 区分，POST /submit 是强制
 *     submit=True 的别名。两条路径都已实测（别名那条传 submit:false 仍返回提交校验错误）。
 *     本实现统一走 PUT —— 一次请求即可携带 lines + submit + 乐观锁基准，无需分支。
 *  2. **时间口径（2026-10 已变更）**：后端统一使用**北京时间**，接口返回的是
 *     「北京时间 naive」字符串（如 "2026-10-15T18:00:00"），**可直接按本地时间展示**。
 *     此前后端用 UTC 基准（utcnow()），曾导致"按本地解析比 remaining_seconds 多 8 小时"；
 *     现在 backend 的 app_now() 已是北京时间基准，前端也同步改为本地解释（见
 *     parseServerDateTime）。倒计时仍以 `remaining_seconds` 为基准 + 本地单调漂移，
 *     这样即使前后端时钟有秒级差异也不会跳变。
 *  3. 后端把 payload 里出现的行**整体覆盖**（price_incl_tax=None 即清空），
 *     所以只能提交"本地发生过变更(dirty)"的行，否则会把已存值清空。
 *  4. Decimal 一律以字符串传输（"40.000" / "0.1300"），前端不做 Number 往返。
 */

// ---------------------------------------------------------------------------
// 常量（PRD 5.2.2 / 10.3）
// ---------------------------------------------------------------------------
/** 手机端分段阈值：> 10 行才分段（FR-RWD-31） */
export const SEGMENT_SIZE = 10
/** 税率字典（PRD 5.2.2 固定 5 档）；后端存 0~1 的 Decimal，如 "0.13" */
export const TAX_RATE_OPTIONS = Object.freeze([
  { value: '0.13', label: '13%' },
  { value: '0.09', label: '9%' },
  { value: '0.06', label: '6%' },
  { value: '0.03', label: '3%' },
  { value: '0', label: '0%' },
])
export const DEFAULT_TAX_RATE = '0.13'
/** 单价上限 9,999,999.99（PRD 5.2.2） */
export const PRICE_MAX = 9999999.99
export const PRICE_MAX_TEXT = '9999999.99'
/** 附件：单张压缩后 ≤ 2MB，每行 ≤ 3 个（FR-RWD-22） */
export const MAX_ATTACHMENTS_PER_LINE = 3
export const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
/** 保存/提交请求超时 15s（FR-RWD-23 / PRD 10.5） */
export const QUOTE_REQUEST_TIMEOUT = 15000
/** 本地草稿 key 前缀（FR-RWD-24） */
export const DRAFT_KEY_PREFIX = 'xj_quote_draft_'

/**
 * 供货商侧路由路径（与 router/menu.js 的 HOME_BY_ROLE.supplier 对齐）。
 * 路由表由基座（task-1）维护，这里集中一处便于对齐；如需改名只改这里。
 */
export const SUPPLIER_ROUTES = Object.freeze({
  list: '/supplier/quotes',
  fill: (rfqId) => `/supplier/quotes/${rfqId}`,
})

// ---------------------------------------------------------------------------
// 服务端时间解析
// ---------------------------------------------------------------------------
/**
 * 解析后端 datetime 字符串。
 *
 * 后端口径（2026-10 统一）：**应用统一使用北京时间（UTC+8）**，接口返回的是
 * 「北京时间 naive」字符串（无 Z / ±HH:MM 后缀），可按本地时间直接解释并展示。
 *
 * - 无时区后缀 → 按**本地时间**解释（内网单时区部署，后端与用户同处东八区）
 * - 带 Z / ±HH:MM → 交给 Date 按带时区解析，浏览器自动转成当地时间
 *
 * 注意：旧实现把"无后缀"当 UTC 解析再转本地，会额外减 8 小时；backend 已把
 * utcnow() 改为北京时间基准（models.app_now），此处必须同步改为本地解释，
 * 否则截止时间与倒计时会整体偏差 8 小时。
 *
 * @param {string|Date|null} value
 * @returns {Date|null}
 */
export function parseServerDateTime(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = String(value).trim()
  // 必须接受小数秒（后端给 "…T16:15:01.662136"），并识别可选时区后缀
  const matched = text.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/,
  )
  if (!matched) {
    const fallback = new Date(text)
    return Number.isNaN(fallback.getTime()) ? null : fallback
  }
  const [, y, mo, d, h = '0', mi = '0', s = '0', frac = '', zone] = matched
  const ms = frac ? Math.round(Number(`0.${frac}`) * 1000) : 0

  if (zone) {
    // 带时区后缀：先按 UTC 组装，再由 Date 转成本地展示
    const utc = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), ms)
    if (zone === 'Z') return new Date(utc)
    const sign = zone.startsWith('-') ? -1 : 1
    const parts = zone.replace(/[+-]/, '').replace(':', '').match(/\d{2}/g) || ['0', '0']
    return new Date(utc - sign * (Number(parts[0]) * 60 + Number(parts[1])) * 60000)
  }

  // 无时区后缀 → 北京时间 naive，直接按本地时间解释
  return new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), ms)
}

/**
 * 后端北京时间 naive → 本地 "YYYY-MM-DD HH:mm"
 * 前提：设备时区为东八区（内网单时区部署）。倒计时不受此影响——它一律用
 * remaining_seconds，不依赖本机时区。
 */
export function formatServerDateTime(value, { empty = '—' } = {}) {
  const date = parseServerDateTime(value)
  if (!date) return empty
  const p = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}`
}

/** 后端北京时间 naive → 本地 "MM-DD HH:mm"（列表紧凑用；前提同上：设备东八区） */
export function formatServerDateTimeShort(value, { empty = '—' } = {}) {
  const full = formatServerDateTime(value, { empty })
  return full === empty ? empty : full.slice(5)
}

/**
 * 倒计时时钟：以后端 remaining_seconds 为基准，用本地时间做单调漂移。
 * 这样页面停留 10 分钟、挂后台再回来，剩余时间依然准确，且不受设备时区设置影响。
 * @param {number|null|undefined} remainingSeconds
 * @returns {{ left: () => number|null }}
 */
export function createCountdown(remainingSeconds) {
  const base = remainingSeconds === null || remainingSeconds === undefined ? NaN : Number(remainingSeconds)
  const t0 = Date.now()
  return {
    left() {
      if (!Number.isFinite(base)) return null
      return Math.floor(base - (Date.now() - t0) / 1000)
    },
  }
}

/**
 * 剩余时间的紧急度（设计稿 03-2：<24h 危险色，2 天档用琥珀，3 天以上灰）
 * @returns {'danger'|'warn'|'muted'|'closed'}
 */
export function remainingTone(leftSeconds) {
  if (leftSeconds === null || !Number.isFinite(Number(leftSeconds))) return 'muted'
  const left = Number(leftSeconds)
  if (left <= 0) return 'closed'
  if (left <= 24 * 3600) return 'danger'
  if (left < 72 * 3600) return 'warn'
  return 'muted'
}

/** 紧凑剩余时间（appbar 徽标用，设计稿写"剩余 2天4时"） */
export function formatRemainingCompact(seconds, { empty = '—' } = {}) {
  if (seconds === null || seconds === undefined) return empty
  const total = Number(seconds)
  if (!Number.isFinite(total)) return empty
  if (total <= 0) return '已截止'
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) return `${days}天${hours}时`
  if (hours > 0) return `${hours}时${minutes}分`
  return `${minutes}分`
}

/** 本地日期 YYYY-MM-DD（原生 date 控件的 min 用） */
export function localDateISO(date = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`
}

/** 截止时间 + 1 年（原生 date 控件的 max 用，PRD 5.2.2 校验） */
export function arrivalMaxDate(deadline) {
  const date = parseServerDateTime(deadline)
  if (!date) return ''
  const next = new Date(date.getTime())
  next.setFullYear(next.getFullYear() + 1)
  return localDateISO(next)
}

// ---------------------------------------------------------------------------
// 输入清洗与校验
// ---------------------------------------------------------------------------
/** 只保留数字与一个小数点、整数位 ≤7、小数位 ≤2（`type="text"` 手动清洗，避免安卓丢小数点） */
export function sanitizePrice(raw) {
  let text = String(raw ?? '').replace(/[^\d.]/g, '')
  const dot = text.indexOf('.')
  if (dot >= 0) {
    text = `${text.slice(0, dot + 1)}${text.slice(dot + 1).replace(/\./g, '')}`
    const [intPart, decPart] = text.split('.')
    text = `${intPart.slice(0, 7)}.${decPart.slice(0, 2)}`
  } else {
    text = text.slice(0, 7)
  }
  // ".5" → "0.5"：安卓数字键盘上先按小数点是常见操作
  if (text.startsWith('.')) text = `0${text}`
  return text
}

/** 金额类（MOQ）：整数位 ≤7、小数位 ≤3（后端 qty() 保留 3 位） */
export function sanitizeDecimal3(raw) {
  let text = String(raw ?? '').replace(/[^\d.]/g, '')
  const dot = text.indexOf('.')
  if (dot >= 0) {
    text = `${text.slice(0, dot + 1)}${text.slice(dot + 1).replace(/\./g, '')}`
    const [intPart, decPart] = text.split('.')
    text = `${intPart.slice(0, 7)}.${decPart.slice(0, 3)}`
  } else {
    text = text.slice(0, 7)
  }
  if (text.startsWith('.')) text = `0${text}`
  return text
}

/** 非负整数（交期天数，上限 3650 = 后端 le=3650） */
export function sanitizeInt(raw, max = 3650) {
  const text = String(raw ?? '').replace(/\D/g, '').slice(0, 4)
  if (text === '') return ''
  return String(Math.min(Number(text), max))
}

/**
 * 单价校验。0 是合法报价（表示赠送/免费，PRD 5.2.2），所以「空」与「0」必须区分。
 * @returns {{filled: boolean, ok: boolean, message: string}}
 */
export function validatePrice(text) {
  const value = String(text ?? '').trim()
  if (value === '') return { filled: false, ok: true, message: '' }
  if (value === '.') return { filled: true, ok: false, message: '请输入有效金额' }
  if (!/^\d{1,7}(\.\d{1,2})?$|^\d{1,7}\.$/.test(value)) {
    return { filled: true, ok: false, message: '最多 2 位小数，且不超过 9,999,999.99' }
  }
  if (Number(value) > PRICE_MAX) {
    return { filled: true, ok: false, message: `不得超过 ${PRICE_MAX_TEXT}` }
  }
  return { filled: true, ok: true, message: '' }
}

/** 报价是否已填：单价非空且合法即视为已填（0 也算已填） */
export function isRowFilled(row) {
  const value = String(row?.priceInclTax ?? '').trim()
  if (value === '') return false
  return validatePrice(value).ok
}

// ---------------------------------------------------------------------------
// 行模型
// ---------------------------------------------------------------------------
function pickQuoteValue(quote, key, fallback = '') {
  const value = quote?.[key]
  return value === null || value === undefined ? fallback : String(value)
}

/**
 * SupplierRfqLineOut → 可编辑行模型。
 * 物料信息（材料名称/规格/单位/采购数量）只读，**不放进可写字段**（FR-SUP-07）。
 */
export function createRow(line) {
  const quote = line?.quote || null
  const row = {
    // —— 只读物料信息 ——
    lineUid: line?.line_uid || '',
    seq: Number(line?.seq || 0),
    materialName: line?.material_name || '',
    spec: line?.spec || '',
    unit: line?.unit || '',
    quantity: pickQuoteValue(line, 'quantity', '0'),
    // —— 可写报价字段 ——
    priceInclTax: quote ? pickQuoteValue(quote, 'price_incl_tax') : '',
    taxIncluded: quote ? quote.tax_included !== false : true,
    taxRate: quote ? pickQuoteValue(quote, 'tax_rate', '') : '',
    moq: quote ? pickQuoteValue(quote, 'moq') : '',
    leadTimeDays: quote && quote.lead_time_days !== null && quote.lead_time_days !== undefined
      ? String(quote.lead_time_days)
      : '',
    arrivalDate: quote ? pickQuoteValue(quote, 'arrival_date') : '',
    remark: quote ? pickQuoteValue(quote, 'remark') : '',
    attachments: Array.isArray(quote?.attachments) ? quote.attachments.map((item) => ({ ...item })) : [],
  }
  if (!row.taxRate) row.taxRate = DEFAULT_TAX_RATE
  // dirty 判定基准：打开页面时的原值（不含只读物料字段）
  row._init = serializeWritable(row)
  return row
}

export function createRows(detail) {
  return Array.isArray(detail?.lines) ? detail.lines.map(createRow) : []
}

function serializeWritable(row) {
  return JSON.stringify({
    priceInclTax: String(row.priceInclTax ?? ''),
    taxIncluded: Boolean(row.taxIncluded),
    taxRate: String(row.taxRate ?? ''),
    moq: String(row.moq ?? ''),
    leadTimeDays: String(row.leadTimeDays ?? ''),
    arrivalDate: String(row.arrivalDate ?? ''),
    remark: String(row.remark ?? ''),
    attachments: (row.attachments || []).map((a) => a?.filename || '').join('|'),
  })
}

/** 行是否有未保存的本地变更 */
export function isRowDirty(row) {
  return serializeWritable(row) !== row._init
}

/** 折叠区已填项数（用于"3 项已填 ›"） */
export function extraFilledCount(row) {
  let count = 0
  if (row.taxIncluded === false && row.taxRate) count += 1
  if (String(row.moq ?? '').trim() !== '') count += 1
  if (String(row.leadTimeDays ?? '').trim() !== '') count += 1
  if (String(row.arrivalDate ?? '').trim() !== '') count += 1
  if (String(row.remark ?? '').trim() !== '') count += 1
  if ((row.attachments || []).length > 0) count += 1
  return count
}

/**
 * 不含税单价（只读展示）：含税 / (1 + 税率)；开关为「否」时填的即不含税价。
 * 与 backend/app/utils.py::calc_price_excl_tax 保持一致。
 */
export function computePriceExclTax(row) {
  const raw = String(row?.priceInclTax ?? '').trim()
  if (raw === '') return ''
  const price = Number(raw)
  if (!Number.isFinite(price)) return ''
  if (!row?.taxIncluded) return price.toFixed(2)
  const rate = Number(row?.taxRate)
  if (!Number.isFinite(rate) || rate <= 0) return price.toFixed(2)
  return (price / (1 + rate)).toFixed(2)
}

/** 整单填写统计（StickyBar 的"已填 x / y 行"始终按整单，FR-RWD-31） */
export function sumFilled(rows) {
  const list = Array.isArray(rows) ? rows : []
  const filled = list.filter(isRowFilled).length
  return { filled, total: list.length, unfilled: list.length - filled }
}

/** 未填行号（提交确认弹层按此列出） */
export function unfilledSeqs(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isRowFilled(row)).map((row) => row.seq)
}

/** 行级提示：MOQ 超过采购数量 / 交期与到货日期都空（不阻断，仅提示） */
export function rowWarnings(row) {
  const warnings = []
  const moq = Number(String(row?.moq ?? '').trim())
  const quantity = Number(String(row?.quantity ?? '').trim())
  if (Number.isFinite(moq) && moq > 0 && Number.isFinite(quantity) && moq > quantity) {
    warnings.push(`MOQ ${row.moq} 大于采购数量 ${row.quantity}，请确认可满足`)
  }
  if (isRowFilled(row) && String(row?.leadTimeDays ?? '').trim() === '' && String(row?.arrivalDate ?? '').trim() === '') {
    warnings.push('交货周期与到货日期至少填一项')
  }
  return warnings
}

// ---------------------------------------------------------------------------
// 分段导航（FR-RWD-31）
// ---------------------------------------------------------------------------
/** @returns {{index:number, from:number, to:number, label:string}[]} */
export function buildSegments(total, size = SEGMENT_SIZE) {
  const count = Math.max(0, Number(total) || 0)
  if (count <= 0) return []
  const step = Math.max(1, Number(size) || SEGMENT_SIZE)
  const segments = []
  for (let start = 0; start < count; start += step) {
    const end = Math.min(start + step, count)
    segments.push({
      index: segments.length,
      from: start + 1,
      to: end,
      label: `${start + 1}~${end}`,
    })
  }
  return segments
}

/** 某一行区间（1-based，含端点）内的未填行数 */
export function segmentUnfilledCount(rows, from, to) {
  return (Array.isArray(rows) ? rows : []).filter(
    (row) => row.seq >= from && row.seq <= to && !isRowFilled(row),
  ).length
}

// ---------------------------------------------------------------------------
// 提交 payload（严格对齐 schemas.QuoteSaveRequest / QuoteLineIn）
// ---------------------------------------------------------------------------
function toPayloadLine(row) {
  const price = String(row.priceInclTax ?? '').trim()
  const moq = String(row.moq ?? '').trim()
  const lead = String(row.leadTimeDays ?? '').trim()
  const remark = String(row.remark ?? '').trim()
  const attachments = (row.attachments || []).filter((item) => item && item.filename)
  return {
    line_uid: row.lineUid,
    price_incl_tax: price === '' ? null : price,
    tax_included: Boolean(row.taxIncluded),
    tax_rate: row.taxRate === '' || row.taxRate === null ? null : String(row.taxRate),
    moq: moq === '' ? null : moq,
    lead_time_days: lead === '' ? null : Number(lead),
    arrival_date: String(row.arrivalDate ?? '').trim() === '' ? null : String(row.arrivalDate).trim(),
    remark: remark === '' ? null : remark,
    // 只提交后端定义的 4 个键，剥掉前端的 _preview（本地 objectURL）等字段
    attachments: attachments.length
      ? attachments.map((item) => ({
          filename: item.filename,
          original_name: item.original_name || item.filename,
          size: Number.isFinite(Number(item.size)) ? Number(item.size) : null,
          url: item.url || null,
        }))
      : null,
  }
}

/**
 * 组装保存/提交请求体。
 * 只发送 dirty 行：后端对 payload 中出现的行做整体覆盖，发送未变更行会白写历史，
 * 而发送"本地为空"的未填行会把服务端已有值清成 null（实测 supplier.py:328-347）。
 * @param {object[]} rows
 * @param {{submit?: boolean, expectedUpdatedAt?: string|null}} options
 */
export function buildSavePayload(rows, { submit = false, expectedUpdatedAt = null } = {}) {
  const lines = (Array.isArray(rows) ? rows : []).filter(isRowDirty).map(toPayloadLine)
  const payload = { lines, submit: Boolean(submit) }
  if (expectedUpdatedAt) payload.expected_updated_at = expectedUpdatedAt
  return payload
}

/** 提交前本地拦截（与后端 40001 的校验口径保持一致） */
export function validateForSubmit(rows) {
  const problems = []
  const missing = unfilledSeqs(rows)
  if (missing.length) {
    problems.push({ type: 'missing_price', seqs: missing })
  }
  const badPrice = (Array.isArray(rows) ? rows : [])
    .filter((row) => {
      const value = String(row.priceInclTax ?? '').trim()
      return value !== '' && !validatePrice(value).ok
    })
    .map((row) => ({ seq: row.seq, message: validatePrice(row.priceInclTax).message }))
  if (badPrice.length) problems.push({ type: 'invalid_price', rows: badPrice })
  const needRate = (Array.isArray(rows) ? rows : [])
    .filter((row) => row.taxIncluded === false && isRowFilled(row) && String(row.taxRate ?? '') === '')
    .map((row) => row.seq)
  if (needRate.length) problems.push({ type: 'missing_tax_rate', seqs: needRate })
  return { ok: problems.length === 0, problems, missing }
}

// ---------------------------------------------------------------------------
// 只读判定（FR-SUP-11 / FR-RWD-25）
// ---------------------------------------------------------------------------
/**
 * @param {object|null} detail SupplierRfqDetail
 * @param {number|null} leftSeconds 实时剩余秒数
 */
export function resolveReadonly(detail, leftSeconds) {
  if (!detail) return false
  if (detail.readonly === true) return true
  if (detail.status === 'closed') return true
  if (leftSeconds !== null && leftSeconds !== undefined && Number(leftSeconds) <= 0) return true
  return false
}

// ---------------------------------------------------------------------------
// 本地草稿（FR-RWD-24）
// ---------------------------------------------------------------------------
export function draftKey(rfqId) {
  return `${DRAFT_KEY_PREFIX}${rfqId}`
}

/**
 * 只把"有本地未保存变更(dirty)的行"写入草稿：
 *  - 语义正确：草稿＝尚未提交到服务端的修改，与乐观锁基准无关；
 *  - 避免假阳性：保存/提交成功后 dirty 归零，草稿会被清掉而不再提示"恢复草稿"。
 */
export function toDraft(rows, updatedAt) {
  const dirtyRows = (Array.isArray(rows) ? rows : []).filter(isRowDirty)
  return {
    updatedAt: updatedAt || '',
    savedAt: new Date().toISOString(),
    lines: dirtyRows.map((row) => ({
      line_uid: row.lineUid,
      price_incl_tax: String(row.priceInclTax ?? ''),
      tax_included: Boolean(row.taxIncluded),
      tax_rate: String(row.taxRate ?? ''),
      moq: String(row.moq ?? ''),
      lead_time_days: String(row.leadTimeDays ?? ''),
      arrival_date: String(row.arrivalDate ?? ''),
      remark: String(row.remark ?? ''),
      attachments: row.attachments || [],
    })),
  }
}

/** 草稿是否有可恢复内容（空草稿不弹提示） */
export function draftHasContent(draft) {
  return Boolean(draft && Array.isArray(draft.lines) && draft.lines.length > 0)
}

/** 草稿回填到行模型（只覆盖可写字段，物料字段仍以服务端为准） */
export function applyDraft(rows, draft) {
  if (!draft || !Array.isArray(draft.lines)) return rows
  const byUid = new Map(draft.lines.map((line) => [line.line_uid, line]))
  return rows.map((row) => {
    const saved = byUid.get(row.lineUid)
    if (!saved) return row
    row.priceInclTax = String(saved.price_incl_tax ?? '')
    row.taxIncluded = saved.tax_included !== false
    row.taxRate = String(saved.tax_rate || DEFAULT_TAX_RATE)
    row.moq = String(saved.moq ?? '')
    row.leadTimeDays = String(saved.lead_time_days ?? '')
    row.arrivalDate = String(saved.arrival_date ?? '')
    row.remark = String(saved.remark ?? '')
    row.attachments = Array.isArray(saved.attachments) ? saved.attachments.map((a) => ({ ...a })) : []
    return row
  })
}

// ---------------------------------------------------------------------------
// 附件
// ---------------------------------------------------------------------------
/** 附件名（拍照压缩后统一 .jpg） */
export function attachmentName(item) {
  return item?.original_name || item?.filename || '附件'
}

/** 列表/详情接口的我的状态 → 徽标文案与语义色（设计稿 03-2） */
export function myStatusBadge(myStatus) {
  if (myStatus === 'partial') return { label: '报价中', tone: 'warn' }
  if (myStatus === 'quoted') return { label: '已提交', tone: 'ok' }
  return { label: '未报价', tone: 'danger' }
}

/** 主按钮文案（设计稿 03-2：去报价 / 继续填报 / 修改报价） */
export function primaryActionLabel(myStatus) {
  if (myStatus === 'partial') return '继续填报'
  if (myStatus === 'quoted') return '修改报价'
  return '去报价'
}
