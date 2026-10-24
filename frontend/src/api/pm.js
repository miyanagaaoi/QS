/**
 * 项目管理接口（CH-002 + CH-005 + CH-007，前缀 /api/pm）
 * ---------------------------------------------------------------------------
 * 与报价模块**完全独立**：不引用 rfq 的任何数据。
 *
 * 三张参考表（工序 / 管理点 / 配套单据）都分两套数据：
 *  - 不传 projectId → 标准模板（**只有管理员**能读改，后端强制）
 *  - 传 projectId   → 该项目副本（管理员与采购员都能改）
 *
 * CH-007：配套单据的审批流转改为「节点列表 + 当前节点」，归档要求改为
 * 「归档文件清单 + 逐项勾选」，并支持列表页多选批量归档。
 */
import { del, download, get, post, put } from './request'

// ---------------------------------------------------------------------------
// 看板与项目
// ---------------------------------------------------------------------------
export function getPmBoard() {
  return get('/pm/board')
}

export function listProjects(params = {}) {
  return get('/pm/projects', params)
}

export function getProject(id) {
  return get(`/pm/projects/${id}`)
}

export function createProject(payload) {
  return post('/pm/projects', payload)
}

export function updateProject(id, payload) {
  return put(`/pm/projects/${id}`, payload)
}

/** 删除项目（仅管理员；级联删除副本与历史） */
export function deleteProject(id) {
  return del(`/pm/projects/${id}`)
}

export function saveProjectStages(id, stages) {
  return put(`/pm/projects/${id}/stages`, stages)
}

export function resetProjectStages(id) {
  return post(`/pm/projects/${id}/stages/reset`)
}

/** 按模板重置该项目三张参考表副本 */
export function resetProjectCopies(id) {
  return post(`/pm/projects/${id}/copies/reset`)
}

// ---------------------------------------------------------------------------
// 施工实施步骤明细
// ---------------------------------------------------------------------------
export function listPmProcesses(projectId) {
  return get('/pm/processes', projectId ? { project_id: projectId } : {})
}

export function createPmProcess(payload, projectId) {
  return post('/pm/processes', payload, { params: projectId ? { project_id: projectId } : {} })
}

export function updatePmProcess(id, payload) {
  return put(`/pm/processes/${id}`, payload)
}

export function deletePmProcess(id) {
  return del(`/pm/processes/${id}`)
}

/** 变更工序状态（后端写一条变更历史） */
export function changePmProcessStatus(id, status, remark) {
  return post(`/pm/processes/${id}/status`, { status, remark: remark || null })
}

/** 更新"进行中"工序的当前进度（只写进度历史，不改状态；CH-006） */
export function updatePmProcessProgress(id, remark) {
  return post(`/pm/processes/${id}/progress`, { remark })
}

/** 工序状态/进度历史（按时间倒序） */
export function listPmProcessLogs(id) {
  return get(`/pm/processes/${id}/logs`)
}

// ---------------------------------------------------------------------------
// 预算决算管理点
// ---------------------------------------------------------------------------
export function listPmCostPoints(projectId) {
  return get('/pm/cost-points', projectId ? { project_id: projectId } : {})
}

export function createPmCostPoint(payload, projectId) {
  return post('/pm/cost-points', payload, { params: projectId ? { project_id: projectId } : {} })
}

export function updatePmCostPoint(id, payload) {
  return put(`/pm/cost-points/${id}`, payload)
}

export function deletePmCostPoint(id) {
  return del(`/pm/cost-points/${id}`)
}

// ---------------------------------------------------------------------------
// 预算决算配套单据（CH-007）
// ---------------------------------------------------------------------------
export function listPmDocuments(projectId) {
  return get('/pm/documents', projectId ? { project_id: projectId } : {})
}

export function createPmDocument(payload, projectId) {
  return post('/pm/documents', payload, { params: projectId ? { project_id: projectId } : {} })
}

export function updatePmDocument(id, payload) {
  return put(`/pm/documents/${id}`, payload)
}

export function deletePmDocument(id) {
  return del(`/pm/documents/${id}`)
}

/** 推进/回退到某个审批节点（节点必须在 flow_nodes 里） */
export function changePmDocumentNode(id, node) {
  return post(`/pm/documents/${id}/node`, { node })
}

/** 勾选/取消某个归档文件 */
export function togglePmDocumentArchive(id, fileName, archived) {
  return post(`/pm/documents/${id}/archive`, { file_name: fileName, archived })
}

/** 列表页多选：批量归档 / 撤销归档（作用于选中单据的全部文件） */
export function batchPmDocumentArchive(ids, archived = true) {
  return post('/pm/documents/archive-batch', { ids, archived })
}

/** 列表页给某张单据追加一条归档文件要求 */
export function addPmDocumentFile(id, payload) {
  return post(`/pm/documents/${id}/files`, payload)
}

/** 单据节点/归档操作历史 */
export function listPmDocumentLogs(id) {
  return get(`/pm/documents/${id}/logs`)
}

// ---------------------------------------------------------------------------
// Excel 导出（CH-009）：每个页面导出当前看到的数据
// ---------------------------------------------------------------------------
/** 看板：多项目进度清单 */
export function exportPmBoard(projectCount = 0) {
  return download('/pm/board/export', { filename: `多项目进度_${projectCount}个项目.xlsx` })
}

/** 工期计划表：某项目的 8 阶段明细 */
export function exportProjectStages(id, name = '') {
  return download(`/pm/projects/${id}/stages/export`, { filename: `工期计划表_${name || id}.xlsx` })
}

/** 施工实施步骤明细（不传 projectId = 标准模板，仅管理员可导） */
export function exportPmProcesses(projectId) {
  return download('/pm/processes/export', {
    params: projectId ? { project_id: projectId } : {},
    filename: '施工实施步骤明细.xlsx',
  })
}

/** 预算决算管理点 */
export function exportPmCostPoints(projectId) {
  return download('/pm/cost-points/export', {
    params: projectId ? { project_id: projectId } : {},
    filename: '预算决算管理点.xlsx',
  })
}

/** 预算决算配套单据 */
export function exportPmDocuments(projectId) {
  return download('/pm/documents/export', {
    params: projectId ? { project_id: projectId } : {},
    filename: '预算决算配套单据.xlsx',
  })
}
