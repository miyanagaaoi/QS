/**
 * 业务状态 → 文案 / 语义色 映射（唯一来源：doc/design/01-design-system.html 第 02 节）
 * ---------------------------------------------------------------------------
 * 无障碍硬约束：状态徽标**必须带文字**，不允许只靠颜色区分（色盲用户 + 黑白打印）。
 * 列表页做列定义（DataTable columns / cardFields）时可直接引用 statusLabel()。
 */

/** tone ↔ 设计令牌语义色 */
export const TONE_CLASS = Object.freeze({
  muted: 'is-muted',
  info: 'is-info',
  warn: 'is-warn',
  ok: 'is-ok',
  danger: 'is-danger',
  best: 'is-best',
  brand: 'is-brand',
})

/**
 * status 取值与后端字面量一致：
 *   rfq.status          draft | published | closed
 *   rfq_supplier.status pending | partial | quoted
 */
export const STATUS_META = Object.freeze({
  draft: { label: '草稿', tone: 'muted', desc: '草稿：未发布' },
  published: { label: '已发布', tone: 'info', desc: '已发布：进行中' },
  closed: { label: '已截止', tone: 'warn', desc: '已截止（超期或手动）' },
  pending: { label: '待报价', tone: 'muted', desc: '供货商尚未开始报价' },
  partial: { label: '报价中', tone: 'warn', desc: '部分行已填写，未提交' },
  quoted: { label: '已报价', tone: 'ok', desc: '已完成提交' },
  best: { label: '最低价', tone: 'best', desc: '本行最低含税单价' },
  unpriced: { label: '未报价', tone: 'danger', desc: '未报价 / 风险提示' },
  disabled: { label: '已停用', tone: 'danger', desc: '账号或档案已停用' },
  enabled: { label: '启用', tone: 'ok', desc: '账号或档案启用中' },
  not_logged_in: { label: '未首次登录', tone: 'warn', desc: '初始密码未修改' },
  admin: { label: '管理员', tone: 'brand', desc: '角色' },
  buyer: { label: '采购员', tone: 'info', desc: '角色' },
  supplier: { label: '供货商', tone: 'muted', desc: '角色' },
})

/**
 * @param {string} status
 * @returns {{label: string, tone: string, desc?: string}}
 */
export function statusMeta(status) {
  if (!status) return { label: '—', tone: 'muted' }
  return STATUS_META[status] || { label: String(status), tone: 'muted' }
}

export function statusLabel(status, fallback = '—') {
  const meta = STATUS_META[status]
  return meta ? meta.label : status ? String(status) : fallback
}

export function statusTone(status) {
  return statusMeta(status).tone
}

/**
 * 分派进度的辅助文案：报价中 3/8 行、已报价 8/8 行
 * @param {string} status pending | partial | quoted
 * @param {number} filled 已填行数
 * @param {number} total 总行数
 */
export function assignProgressText(status, filled, total) {
  const hasCounts = Number.isFinite(filled) && Number.isFinite(total) && total > 0
  const suffix = hasCounts ? ` ${filled}/${total}` : ''
  if (status === 'partial') return `报价中${suffix}`
  if (status === 'quoted') return `已报价${suffix}`
  if (status === 'pending') return `待报价${suffix}`
  return statusLabel(status)
}

export default { STATUS_META, TONE_CLASS, statusMeta, statusLabel, statusTone, assignProgressText }
