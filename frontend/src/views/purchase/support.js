/**
 * 我方侧（采购管理）页面的本地补充调用
 * ---------------------------------------------------------------------------
 * 为什么单独一个文件：`src/api/` 由前端基座（task-1）独占维护，本次不修改其中任何文件。
 * 但 task-3 需要下面几个基座尚未提供的调用，按任务要求"缺失的部分在页面内做最小实现"，
 * 统一收敛到本文件（仍复用 @/api/request 的唯一出口，不自己 new axios）：
 *
 *  1. 字典：GET /api/meta/units | /api/meta/taxes | /api/meta/suppliers
 *     （仓库里没有 src/api/meta.js；字段见 schemas.UnitOut / TaxOut / SupplierOut）
 *  2. Excel 预校验：POST /api/rfqs/import/preview?rfq_id=N
 *     （backend/app/api/rfq.py 的 import_preview 需要 rfq_id 查询参数，
 *      而 @/api/rfq.js 的 previewImport 没有透传该参数，会直接 40001）
 *  3. 比价明细导出：GET /api/reports/rfq-comparison/export
 *     （@/api/report.js 只有 summary 的导出）
 *  4. 页头统计（"共 N 张 · X 张进行中 · Y 张已截止"）需要按状态取 total
 *  5. 已发布且未截止的询价单「追加供货商」：POST /api/rfqs/{id}/append-suppliers
 *     （task-11，后端已实现并实测通过）
 *
 * 真实字段名已用 curl 对齐 backend/app/schemas.py + 运行中的 127.0.0.1:8000。
 */
import { CODE, download, get, requestRaw, upload } from '@/api/request'
import { formatQty } from '@/composables/useFormat'

/** 启用的计量单位（明细行「单位」下拉；UnitOut: id/name/sort/status） */
export function listUnits() {
  return get('/meta/units')
}

/** 启用的税率字典（TaxOut: id/rate(字符串)/label/is_default/status/sort） */
export function listTaxes() {
  return get('/meta/taxes')
}

/** 供货商档案（受邀供货商多选 / 报表供货商筛选；含 contact_name/contact_phone） */
export function listSupplierOptions(params) {
  return get('/meta/suppliers', params)
}

/**
 * Excel 预校验（不落库）。返回 ImportPreviewResult：
 * { total_rows, valid_rows, error_rows, preview[], errors[{row,column,value,reason}],
 *   unknown_units[], token }
 * @param {number} rfqId 目标询价单（必须是本人可编辑的草稿）
 * @param {File} file .xlsx / .xls
 * @param {(percent:number)=>void} [onProgress]
 */
export function previewRfqImport(rfqId, file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return upload(`/rfqs/import/preview?rfq_id=${encodeURIComponent(rfqId)}`, formData, { onProgress })
}

/**
 * 导出视图 A 比价明细 .xlsx
 * @param {{rfq_id:number, only_unquoted?:boolean}} params
 */
export function exportComparison(params, filename = '比价明细.xlsx') {
  return download('/reports/rfq-comparison/export', { params, filename })
}

/**
 * 已发布且**未截止**的询价单追加受邀供货商（task-11）
 * ---------------------------------------------------------------------------
 * 需求："已发布报价单，未截止前，可编辑追加供货商"。
 * 语义：**只追加、不删除**；不触碰明细行与已有报价（已有供货商在截止前仍可填报/修改）；
 *       新追加的供货商立即可填报（看到全部明细、报价列为空）。
 *
 *   POST /api/rfqs/{rfq_id}/append-suppliers
 *   body { "supplier_ids": [3, 4] }       至少 1 个
 *
 * 实测返回（curl 核对，message 原文）：
 *   200 code=0     message="已追加 1 家供货商"
 *                  message="已追加 1 家供货商；跳过 1 家"（混合追加：部分已分派）
 *                  data=RfqDetail（含最新 assignees）
 *   409 code=40900 message="没有新增供货商：鑫达办公"（重复/全部已分派）
 *                  message="草稿状态请直接编辑受邀供货商，无需追加"
 *   403 code=40301 message="该询价单已截止，不可再追加供货商"
 *   403 code=40300 供货商角色调用（已留痕）
 *
 * 为什么用 requestRaw：request.js 默认只返回 data，而"跳过 N 家"这类信息只在
 * 信封的 message 里，必须拿到整封信封；silent:true 让页面按 code 自行提示，
 * 避免与默认 Toast 重复。
 *
 * @param {number} rfqId
 * @param {number[]} supplierIds
 * @returns {Promise<{code:number, message:string, data:object}>}
 */
export function appendRfqSuppliers(rfqId, supplierIds) {
  return requestRaw({
    url: `/rfqs/${rfqId}/append-suppliers`,
    method: 'post',
    data: { supplier_ids: [...supplierIds] },
    silent: true,
  })
}

/**
 * 追加供货商失败 → 归一化为页面可直接分支的提示信息。
 * 页面负责展示与刷新（不在这里弹 Toast，避免三处提示样式不一致）。
 * @param {any} error ApiError
 * @returns {{kind:'closed'|'conflict'|'forbidden'|'missing'|'other', message:string}}
 */
export function appendErrorInfo(error) {
  const message = error?.message || ''
  if (error?.code === CODE.QUOTE_CLOSED) {
    return { kind: 'closed', message: message || '该询价单已截止，不可再追加供货商' }
  }
  if (error?.code === CODE.CONFLICT) {
    return { kind: 'conflict', message: message || '没有可追加的供货商' }
  }
  if (error?.code === CODE.FORBIDDEN) {
    return { kind: 'forbidden', message: message || '无权追加供货商' }
  }
  // 端点尚未部署/被网关拦截（404 / 405）
  if (error?.status === 404 || error?.status === 405 || error?.code === CODE.NOT_FOUND) {
    return { kind: 'missing', message: message || '后端接口未就绪' }
  }
  return { kind: 'other', message: message || '追加失败，请稍后重试' }
}

/**
 * 按状态取单据总数（用于列表页头统计）。silent:true 避免失败时刷屏 Toast。
 * @param {{status?:string, only_mine?:boolean}} extra
 * @returns {Promise<number>}
 */
export function countRfqs(extra = {}) {
  return get('/rfqs', compactParams({ page: 1, page_size: 1, ...extra }), { silent: true })
    .then((data) => Number(data?.meta?.total ?? 0))
    .catch(() => 0)
}

/**
 * 复制文本（催办名单）。navigator.clipboard 在 http 内网地址下不可用，降级 execCommand。
 * @returns {Promise<boolean>}
 */
export async function copyText(text) {
  const value = String(text ?? '')
  if (!value) return false

  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    /* 继续走降级分支 */
  }

  try {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', 'readonly')
    textarea.style.position = 'fixed'
    textarea.style.top = '-1000px'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    textarea.setSelectionRange(0, value.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

/**
 * 剔除空值（''/null/undefined）的可选查询参数。
 * ---------------------------------------------------------------------------
 * 踩坑记录：把 `{date_from: '', date_to: ''}` 直接交给 axios，会被序列化成
 * `?date_from=&date_to=`，后端 `date | None` 解析空串返回 40001
 * （"Input should be a valid date or datetime, input is too short"），
 * 列表页因此整体走 catch 分支、显示"共 0 张"。所有页面的可选筛选参数
 * 一律先过这个函数再下发，不要依赖后端容错。
 *
 * 注意：boolean false 与数字 0 是有效值，会保留。
 *
 * @param {Record<string, any>} params
 * @returns {Record<string, any>}
 */
export function compactParams(params = {}) {
  const result = {}
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined) return
    if (typeof value === 'string' && value.trim() === '') return
    if (Array.isArray(value) && value.length === 0) return
    result[key] = value
  })
  return result
}

/**
 * 比率字段归一化
 * ---------------------------------------------------------------------------
 * 踩坑记录：报表接口的比率出现过**两种形态**——
 *   旧：`"0.1538"` / `"0.0217"`（小数）
 *   新：`"27.3%"` / `"11.8%"` / `"0.0%"`（已格式化百分数字符串）
 * 直接用 useFormat 的 formatPercent（会乘 100）会把 "27.3%" 显示成 "2730.0%"。
 * 因此比率一律先过这里：带 % 的原样用，纯数字按小数换算。
 *
 * @param {string|number|null} value
 * @returns {number|null} 0~1 之间的小数（解析失败返回 null）
 */
export function parseRate(value) {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') {
    return Number.isFinite(value) ? (value > 1 ? value / 100 : value) : null
  }
  const text = String(value).trim()
  const num = Number(text.replace('%', ''))
  if (!Number.isFinite(num)) return null
  return text.includes('%') ? num / 100 : num
}

/**
 * 比率显示：带 % 的字符串原样返回，小数按百分比格式化
 * @param {string|number|null} value
 * @param {{digits?:number, empty?:string}} [options]
 */
export function rateText(value, { digits = 1, empty = '—' } = {}) {
  if (value === null || value === undefined || value === '') return empty
  const text = String(value).trim()
  if (text.endsWith('%')) return text
  const num = Number(text)
  if (!Number.isFinite(num)) return empty
  return `${formatQty(num * 100, { digits, minDigits: digits })}%`
}

/**
 * 仅当目标路由真实存在时才跳转。
 * 基座 router/index.js 与页面由不同人并行开发，直接 push 不存在的路径会打断用户操作。
 * @returns {Promise<boolean>} 是否已跳转
 */
export function safePush(router, path) {
  try {
    const resolved = router.resolve(path)
    if (resolved?.matched?.length) {
      router.push(path)
      return Promise.resolve(true)
    }
  } catch {
    /* 忽略：路由未声明 */
  }
  return Promise.resolve(false)
}
