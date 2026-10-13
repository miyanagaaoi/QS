/**
 * 系统管理接口层（本任务独占目录内实现）
 * ---------------------------------------------------------------------------
 * 为什么这里另有一份而不用 src/api/admin.js：
 *   1. src/api/ 由前端基座（task-1）负责，本任务不得改动；
 *   2. 基座里的 admin.js 尚缺供货商账号、批量导入、日志动作等接口，
 *      且个别路径与后端实测不一致（如档案导出其实是 /supplier-accounts/export）。
 *      这里只做「按实测路径补齐」，底层的 axios 封装、统一错误处理、
 *      Toast 去重、二进制下载全部复用 src/api/request.js（全站唯一 HTTP 出口）。
 *
 * 所有路径均在 2026-10-13 用 admin / Xunjia2026 实测通过（HTTP 200）。
 */
import { ApiError, CODE, download, get, http, post, put, saveBlob, upload } from '@/api/request'

// 与后端 settings.max_upload_size_mb（backend/app/config.py，默认 10）保持一致
export const MAX_IMPORT_BYTES = 10 * 1024 * 1024
// 与后端 settings.import_max_rows（默认 2000，FR-IMP-06）保持一致
export const IMPORT_MAX_ROWS = 2000
export const IMPORT_ERROR_REPORT_NAME = '供货商账号导入错误报告.xlsx'

// ---------------------------------------------------------------------------
// A. 我方账号（FR-ACC-01~07）
// ---------------------------------------------------------------------------
export function listUsers(params) {
  return get('/admin/users', params)
}

export function createUser(data) {
  return post('/admin/users', data)
}

export function updateUser(id, data) {
  return put(`/admin/users/${id}`, data)
}

/** 409/40900 时后端带原文原因（如"……无法停用最后一个启用的管理员"），调用方需原文展示 */
export function toggleUserStatus(id, config = {}) {
  return post(`/admin/users/${id}/toggle-status`, {}, config)
}

export function resetUserPassword(id, data) {
  return post(`/admin/users/${id}/reset-password`, data)
}

// ---------------------------------------------------------------------------
// B. 供货商账号（FR-ACC-08/09/14）
// ---------------------------------------------------------------------------
export function listSupplierAccounts(params) {
  return get('/admin/supplier-accounts', params)
}

export function createSupplierAccount(data) {
  return post('/admin/supplier-accounts', data)
}

export function toggleSupplierAccountStatus(id, config = {}) {
  return post(`/admin/supplier-accounts/${id}/toggle-status`, {}, config)
}

export function resetSupplierAccountPassword(id, data) {
  return post(`/admin/supplier-accounts/${id}/reset-password`, data)
}

/** 导出供货商账号清单（xlsx，不含密码） */
export function exportSupplierAccounts(params = {}, filename = '供货商账号清单.xlsx') {
  return download('/admin/supplier-accounts/export', { params, filename })
}

// ---------------------------------------------------------------------------
// C. 批量导入（FR-ACC-10~13）—— 预校验不落库，确认后才写库
// ---------------------------------------------------------------------------
/** 下载导入模板（xlsx 二进制） */
export function downloadImportTemplate(filename = '供货商账号导入模板.xlsx') {
  return download('/admin/supplier-accounts/import-template', { filename })
}

/** 上传 .xlsx 预校验；返回 { total, valid, invalid, errors[{row,column,value,reason}], token } */
export function previewImport(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return upload('/admin/supplier-accounts/import', formData, { onProgress })
}

/** 确认导入；token 单次有效，重复使用后端返回 40001 */
export function confirmImport(token) {
  return post('/admin/supplier-accounts/import/confirm', { token })
}

/**
 * 导出错误报告（xlsx）：后端需要重新上传同一个文件，不落库、不签发 token。
 *
 * ⚠️ 这里刻意不走 request.js 的 download()：download() 不接受 headers，
 *    而 axios 实例的默认 Content-Type 是 application/json；
 *    axios 一旦检测到「FormData + application/json」，会把 FormData 转成 JSON 发出去，
 *    后端的 `file: UploadFile = File(...)` 就收不到文件，接口直接 HTTP 400。
 *    因此这里与 request.js 的 upload() 保持同一手法：显式声明 multipart/form-data，
 *    让浏览器补上 boundary（实测 HTTP 200，返回 xlsx）。
 */
export async function exportImportErrorReport(file, filename = IMPORT_ERROR_REPORT_NAME) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await http.request({
    url: '/admin/supplier-accounts/import/error-report',
    method: 'post',
    data: formData,
    responseType: 'blob',
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  const blob = response.data
  const contentType = response.headers?.['content-type'] || ''

  // 后端异常时可能以 JSON 信封返回（此时 responseType=blob 拿到的是 Blob）
  if (contentType.includes('application/json')) {
    let body = null
    try {
      body = JSON.parse(await blob.text())
    } catch {
      body = null
    }
    throw new ApiError(
      body?.message || '导出错误报告失败',
      Number(body?.code ?? CODE.SERVER),
      body?.data ?? null,
      response.status,
    )
  }

  saveBlob(blob, filename)
  return { filename }
}

// ---------------------------------------------------------------------------
// D. 供货商档案（FR-MST-03/04）
// ---------------------------------------------------------------------------
export function listSuppliers(params) {
  return get('/admin/suppliers', params)
}

export function createSupplier(data) {
  return post('/admin/suppliers', data)
}

export function updateSupplier(id, data) {
  return put(`/admin/suppliers/${id}`, data)
}

/** 停用档案会同步停用其绑定账号；启用档案不会自动启用账号（后端 message 里已说明） */
export function toggleSupplierStatus(id) {
  return post(`/admin/suppliers/${id}/toggle-status`, {}, { silent: true })
}

// ---------------------------------------------------------------------------
// E. 字典：计量单位 / 税率（FR-MST-01/02）
// ---------------------------------------------------------------------------
/** 单位列表项含 referenced_count（被 rfq_line 引用的行数，用于灰化"删除/停用"提示） */
export function listUnits(params) {
  return get('/admin/units', params)
}

export function createUnit(data) {
  return post('/admin/units', data)
}

export function updateUnit(id, data) {
  return put(`/admin/units/${id}`, data)
}

export function listTaxes(params) {
  return get('/admin/taxes', params)
}

export function createTax(data) {
  return post('/admin/taxes', data)
}

export function updateTax(id, data) {
  return put(`/admin/taxes/${id}`, data)
}

// ---------------------------------------------------------------------------
// F. 操作日志（FR-LOG-01~04，只读）
// ---------------------------------------------------------------------------
export function listAuditLogs(params) {
  return get('/admin/audit-logs', params)
}

/** 动作类型下拉数据源（后端去重返回，如 auth.login / user.toggle_status） */
export function listAuditActions() {
  return get('/admin/audit-logs/actions')
}

// ---------------------------------------------------------------------------
// 前端 CSV 导出兜底
// ---------------------------------------------------------------------------
/**
 * 后端未提供「操作日志导出」与「我方账号清单导出」接口（实测无该路由），
 * 这里用带 BOM 的 CSV 兜底：Excel 可直接双击打开，中文不乱码。
 * @param {string} filename 形如 操作日志_20261013.csv
 * @param {Array<{label:string, value:string|number}>} columns
 * @param {Array<Record<string, any>>} rows
 */
export function downloadCsv(filename, columns, rows) {
  const escape = (value) => {
    const text = value === null || value === undefined ? '' : String(value)
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const head = columns.map((col) => escape(col.label)).join(',')
  const body = rows
    .map((row) => columns.map((col) => escape(row[col.key])).join(','))
    .join('\r\n')
  // \ufeff：BOM，保证 Excel 以 UTF-8 打开（否则中文乱码）
  const blob = new Blob([`\ufeff${head}\r\n${body}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

/** 日期戳，用于导出文件名：20261013 */
export function dateStamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
}

export { download }
