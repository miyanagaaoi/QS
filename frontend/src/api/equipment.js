/**
 * 设备管理接口（CH-014，前缀 /api/eq）
 * ---------------------------------------------------------------------------
 * 与「采购报价」「项目管理」完全独立。
 * 列表接口统一返回分页结构：{ items, meta:{page,page_size,total} }。
 * 金额一律是字符串（后端 Decimal 序列化）。
 * 「距到期天数」由后端实时计算（days_to_warranty / days_to_expire / days_to_plan），
 * 前端只按阈值上色，不自己算。
 */
import { del, download, get, post, put, upload } from './request'

// ---------------------------------------------------------------------------
// 字典与看板
// ---------------------------------------------------------------------------
/** 下拉字典 + 预警阈值（状态/事件类型/检验类型等） */
export function getEqMeta() {
  return get('/eq/meta')
}

/** 统计看板：状态分布、等级分布、预警、事件统计 */
export function getEqBoard() {
  return get('/eq/board')
}

// ---------------------------------------------------------------------------
// 设备主台账
// ---------------------------------------------------------------------------
export function listEqAssets(params = {}) {
  return get('/eq/assets', params)
}

export function getEqAsset(id) {
  return get(`/eq/assets/${id}`)
}

export function createEqAsset(payload) {
  return post('/eq/assets', payload)
}

export function updateEqAsset(id, payload) {
  return put(`/eq/assets/${id}`, payload)
}

export function deleteEqAsset(id) {
  return del(`/eq/assets/${id}`)
}

// ---------------------------------------------------------------------------
// 四类子台账（kind: events | meters | specials | spares）
// ---------------------------------------------------------------------------
const CHILD_PATH = {
  events: '/eq/events',
  meters: '/eq/meters',
  specials: '/eq/specials',
  spares: '/eq/spares',
}

export function listEqChildren(kind, params = {}) {
  return get(CHILD_PATH[kind], params)
}

export function createEqChild(kind, payload) {
  return post(CHILD_PATH[kind], payload)
}

export function updateEqChild(kind, id, payload) {
  return put(`${CHILD_PATH[kind]}/${id}`, payload)
}

export function deleteEqChild(kind, id) {
  return del(`${CHILD_PATH[kind]}/${id}`)
}

// ---------------------------------------------------------------------------
// 导入 / 导出
// ---------------------------------------------------------------------------
/** 导出某张台账（kind: assets|events|meters|specials|spares） */
export function exportEq(kind, filename) {
  return download(`/eq/${kind}/export`, { filename: filename || `${kind}.xlsx` })
}

/** 导入某张台账（上传 xlsx，逐行校验） */
export function importEq(kind, file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return upload(`/eq/${kind}/import`, form, { onProgress })
}

/** 下载导入模板（5 张表各一个 sheet） */
export function downloadEqTemplate() {
  return download('/eq/import-template', { filename: '设备台账导入模板.xlsx' })
}
