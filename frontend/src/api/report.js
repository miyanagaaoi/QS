/**
 * 统计报表接口（PRD 7.4）
 * 返回结构见 schemas.py：ComparisonResult（视图 A）/ SummaryResult（视图 B）。
 */
import { download, get } from './request'

/** 视图 A：单张询价单多供货商比价 @param {{rfq_id:number}} params */
export function getRfqComparison(params) {
  return get('/reports/rfq-comparison', params)
}

/** 视图 B：汇总统计 @param {{date_from?:string,date_to?:string,...}} params */
export function getSummary(params) {
  return get('/reports/summary', params)
}

/** 导出汇总 .xlsx */
export function exportSummary(params, filename = '报价统计汇总.xlsx') {
  return download('/reports/summary/export', { params, filename })
}

// 注意（前后端接口一致性校验 2026-10-13）：
// PRD 7.4 的 GET /reports/material-trend 标注为 P1，本期后端未实现。
// 基座原预留的 getMaterialTrend() 无任何页面调用（死接口），已删除以免被误用；
// 后端实现该端点后，再在此处补回同名封装。
