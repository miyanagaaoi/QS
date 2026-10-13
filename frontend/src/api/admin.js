/**
 * 系统管理接口（PRD 7.5）
 * 请求体字段以 backend/app/schemas.py 为准（InternalUserCreate / SupplierCreate / UnitIn / TaxIn …）。
 * 所有接口仅 admin 可调用，非 admin 会被后端返回 40300。
 *
 * 注意：本模块是按 PRD 7.5 建立的接口薄封装基线，当前**无页面直接 import**。
 * 实际使用方：views/system/adminApi.js（账号管理 / 供货商档案 / 字典维护 / 操作日志页）。
 * 即同一后端接口在本项目存在两处前端封装（本模块 + views/system/adminApi.js）。
 * 修改后端接口时请同步检查实际使用方，避免改一处漏一处。
 * 已清理的死接口：/admin/suppliers/export 后端不存在（仅保留 /admin/supplier-accounts/export）。
 */
import { get, post, put, upload } from './request'

// —— 我方账号 ——
export function listUsers(params) {
  return get('/admin/users', params)
}
export function createUser(data) {
  return post('/admin/users', data)
}
export function updateUser(id, data) {
  return put(`/admin/users/${id}`, data)
}
export function resetUserPassword(id, data) {
  return post(`/admin/users/${id}/reset-password`, data)
}
export function toggleUserStatus(id) {
  return post(`/admin/users/${id}/toggle-status`, {})
}

// —— 供货商档案 ——
export function listSuppliers(params) {
  return get('/admin/suppliers', params)
}
export function createSupplier(data) {
  return post('/admin/suppliers', data)
}
export function updateSupplier(id, data) {
  return put(`/admin/suppliers/${id}`, data)
}

// —— 供货商账号批量导入 / 导出 ——
export function importSupplierAccounts(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return upload('/admin/supplier-accounts/import', formData, { onProgress })
}

// 注意（前后端接口一致性校验 2026-10-13）：
// 后端只有 GET /admin/supplier-accounts/export，不存在 /admin/suppliers/export。
// 基座原预留的 exportSupplierAccounts() 路径错误且无任何页面调用（死接口），已删除；
// 账号管理/供货商档案页请使用 views/system/adminApi.js 的 exportSupplierAccounts()（路径正确）。

// —— 字典：计量单位 / 税率 ——
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

// —— 操作日志 ——
export function listAuditLogs(params) {
  return get('/admin/audit-logs', params)
}
