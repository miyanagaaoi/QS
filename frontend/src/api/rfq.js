/**
 * 询价单接口（PRD 7.2）
 * ---------------------------------------------------------------------------
 * 本文件是「薄封装」：路径按 PRD 7.2 固定，请求体/查询串字段一律以
 * backend/app/schemas.py 为准（RfqCreate / RfqUpdate / RfqLineIn / ImportConfirmRequest …），
 * 因此这里只做参数透传，不在前端二次定义字段名。
 * 金额与数量在前后端之间一律是字符串（Decimal 序列化），不要用 Number 直接算。
 */
import { API_BASE, del, download, get, post, put, upload } from './request'

/** 列表（分页 + 筛选，后端按角色过滤） @param {{page?:number,page_size?:number,...}} params */
export function listRfqs(params) {
  return get('/rfqs', params)
}

/** 新建草稿 @param {object} data RfqCreate */
export function createRfq(data) {
  return post('/rfqs', data)
}

/** 详情（含明细行、受邀供货商、报价进度） */
export function getRfq(id) {
  return get(`/rfqs/${id}`)
}

/** 编辑草稿 @param {object} data RfqUpdate */
export function updateRfq(id, data) {
  return put(`/rfqs/${id}`, data)
}

/** 删除草稿 */
export function deleteRfq(id) {
  return del(`/rfqs/${id}`)
}

/** 发布（生成分派） */
export function publishRfq(id, data) {
  return post(`/rfqs/${id}/publish`, data ?? {})
}

/** 撤回为草稿（作废已有报价，留快照） */
export function withdrawRfq(id, data) {
  return post(`/rfqs/${id}/withdraw`, data ?? {})
}

/** 手动截止 */
export function closeRfq(id, data) {
  return post(`/rfqs/${id}/close`, data ?? {})
}

/** 报价进度（各家状态） */
export function getRfqProgress(id) {
  return get(`/rfqs/${id}/progress`)
}

/** 各家报价明细（报表用；供货商调用返回 40300） */
export function getRfqQuotes(id, params) {
  return get(`/rfqs/${id}/quotes`, params)
}

/** Excel 预校验：上传返回预览与错误清单（含 token 供确认导入使用） */
export function previewImport(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return upload('/rfqs/import/preview', formData, { onProgress })
}

/** 确认导入 @param {object} data ImportConfirmRequest */
export function confirmImport(data) {
  return post('/rfqs/import/confirm', data)
}

/** 导入模板下载地址（若需带 token 请用 downloadImportTemplate） */
export const IMPORT_TEMPLATE_URL = `${API_BASE}/rfqs/import/template`

/** 下载导入模板（自动带 token） */
export function downloadImportTemplate(filename = '询价单导入模板.xlsx') {
  return download('/rfqs/import/template', { filename })
}

/** 导出单张询价单 .xlsx */
export function exportRfq(id, filename) {
  return download(`/rfqs/${id}/export`, { filename: filename || `询价单-${id}.xlsx` })
}
