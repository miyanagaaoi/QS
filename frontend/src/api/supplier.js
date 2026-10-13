/**
 * 供货商报价接口（PRD 7.3）
 * ---------------------------------------------------------------------------
 * 安全约束：后端从 JWT 解析 supplier_id，前端**绝不允许**传 supplier_id 参数
 * （PRD 要求：若传入则忽略并记录告警）。请勿在参数里带 supplier_id。
 *
 * 实际使用方（2026-10-13 逐个核对，非"无页面引用"）：
 *   - views/supplier/QuoteList.vue → listSupplierRfqs()
 *   - views/supplier/QuoteFill.vue → getSupplierRfq()
 *   - 保存/提交报价、附件上传、改价历史等路径在 views/supplier/quoteModel.js 内单独封装
 *     （未走本模块），改后端接口时请一并检查该文件的路径表。
 * 注：本模块 saveSupplierQuotes / submitSupplierQuotes / listSupplierQuoteHistory 三个封装
 *     对应的后端端点均已在 openapi 中存在（PUT /supplier/rfqs/{rfq_id}/quotes、
 *     POST /supplier/rfqs/{rfq_id}/submit、GET /supplier/quotes/history），保留作为契约基线。
 */
import { get, post, put } from './request'

/** 待报价列表（仅分派给本公司的单据） */
export function listSupplierRfqs(params) {
  return get('/supplier/rfqs', params)
}

/** 填报页数据（物料 + 本公司已填值；含 readonly / updated_at 乐观锁基准） */
export function getSupplierRfq(id) {
  return get(`/supplier/rfqs/${id}`)
}

/**
 * 保存报价（可只填部分行）
 * @param {number} id
 * @param {{lines: object[], submit?: boolean, expected_updated_at?: string}} data QuoteSaveRequest
 */
export function saveSupplierQuotes(id, data) {
  return put(`/supplier/rfqs/${id}/quotes`, data)
}

/** 提交报价（后端校验全行已填） */
export function submitSupplierQuotes(id, data) {
  return post(`/supplier/rfqs/${id}/submit`, data ?? {})
}

/** 本公司历史报价 */
export function listSupplierQuoteHistory(params) {
  return get('/supplier/quotes/history', params)
}
