/**
 * 格式化工具集（金额 / 数量 / 日期 / 剩余时间）
 * ---------------------------------------------------------------------------
 * 重要：后端把金额与数量序列化为**字符串**（Decimal → str，见 backend/app/schemas.py），
 * 目的是避免 JS 浮点误差。因此：
 *   - 展示时用本文件的 formatMoney / formatQty（内部转 Number 仅用于显示）；
 *   - 参与提交或计算时**直接透传原字符串**，不要转 Number 再拼回去。
 */

const moneyFormatter = new Intl.NumberFormat('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const EMPTY = '—'

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** 金额（带 ¥，两位小数），空值显示 — */
export function formatMoney(value, { symbol = '¥', empty = EMPTY } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  const sign = n < 0 ? '-' : ''
  return `${sign}${symbol}${moneyFormatter.format(Math.abs(n))}`
}

/** 金额（不带符号，两位小数） */
export function formatAmount(value, { empty = EMPTY } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  return moneyFormatter.format(n)
}

/** 数量 / 单价等数值：默认去掉无意义的尾随 0 */
export function formatQty(value, { digits = 3, empty = EMPTY, minDigits = 0 } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: digits,
  }).format(n)
}

/** 税率：0.13 → 13%；也接受 '0.13' */
export function formatTaxRate(value, { digits = 1, empty = EMPTY } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  return `${formatQty(n * 100, { digits, minDigits: digits })}%`
}

/** 百分比：后端可能直接给 '0.35' 这种字符串 */
export function formatPercent(value, { digits = 1, empty = EMPTY } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  return `${formatQty(n * 100, { digits, minDigits: digits })}%`
}

/** 相对差额：(最高-最低)/最低，正数补 + */
export function formatDiffRate(value, { digits = 1, empty = EMPTY } = {}) {
  const n = toNumberOrNull(value)
  if (n === null) return empty
  const text = formatQty(n * 100, { digits, minDigits: digits })
  return n > 0 ? `+${text}%` : `${text}%`
}

/** 后端返回 'YYYY-MM-DDTHH:mm:ss'（本地无时区），手写解析以兼容 iOS Safari */
export function parseDateTime(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const matched = String(value)
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/)
  if (!matched) {
    const fallback = new Date(value)
    return Number.isNaN(fallback.getTime()) ? null : fallback
  }
  const [, y, mo, d, h = '0', mi = '0', s = '0'] = matched
  return new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s))
}

function pad(n) {
  return String(n).padStart(2, '0')
}

/** YYYY-MM-DD */
export function formatDate(value, { empty = EMPTY } = {}) {
  const date = parseDateTime(value)
  if (!date) return empty
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** YYYY-MM-DD HH:mm */
export function formatDateTime(value, { empty = EMPTY, withSeconds = false } = {}) {
  const date = parseDateTime(value)
  if (!date) return empty
  const head = `${formatDate(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  return withSeconds ? `${head}:${pad(date.getSeconds())}` : head
}

/** MM-DD HH:mm（列表紧凑场景） */
export function formatDateTimeShort(value, { empty = EMPTY } = {}) {
  const date = parseDateTime(value)
  if (!date) return empty
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 日期时间输入框用的本地值 YYYY-MM-DDTHH:mm */
export function toDateTimeInputValue(value) {
  const date = parseDateTime(value)
  if (!date) return ''
  return `${formatDate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 距截止的剩余时间：'2 天 3 小时' / '3 小时 12 分' / '已截止' */
export function formatRemaining(seconds, { empty = EMPTY } = {}) {
  if (seconds === null || seconds === undefined || seconds === '') return empty
  const total = Number(seconds)
  if (!Number.isFinite(total)) return empty
  if (total <= 0) return '已截止'
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分`
}

/** 计算距截止秒数（本地时间，单位秒；已过期为负数） */
export function secondsUntil(deadline, from = new Date()) {
  const date = parseDateTime(deadline)
  if (!date) return null
  return Math.floor((date.getTime() - from.getTime()) / 1000)
}

/** 是否临近截止（默认 24 小时内，PRD 10.2 供货商列表要求醒目提示） */
export function isDeadlineNear(deadline, hours = 24) {
  const left = secondsUntil(deadline)
  return left !== null && left > 0 && left <= hours * 3600
}

export function formatFileSize(bytes, { empty = EMPTY } = {}) {
  const n = toNumberOrNull(bytes)
  if (n === null) return empty
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

/** 组装式用法：const { formatMoney } = useFormat() */
export function useFormat() {
  return {
    formatMoney,
    formatAmount,
    formatQty,
    formatTaxRate,
    formatPercent,
    formatDiffRate,
    formatDate,
    formatDateTime,
    formatDateTimeShort,
    toDateTimeInputValue,
    formatRemaining,
    secondsUntil,
    isDeadlineNear,
    formatFileSize,
    parseDateTime,
    EMPTY,
  }
}

export default useFormat
