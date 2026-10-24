/**
 * 项目管理接口（CH-002 + CH-005，前缀 /api/pm）
 * ---------------------------------------------------------------------------
 * 与报价模块**完全独立**：不引用 rfq 的任何数据。
 *
 * CH-005 起三张参考表分"标准模板"与"项目副本"两套数据：
 *  - 不传 projectId → 标准模板（**只有管理员**能读/改，后端强制）
 *  - 传 projectId   → 该项目副本（管理员与采购员都能改）
 * 副本在首次访问时按模板自动补齐，也可以在项目里"按模板重置"。
 */
import { del, get, post, put } from './request'

/** 看板汇总：summary / stage_distribution / projects / upcoming（含工序完成数） */
export function getPmBoard() {
  return get('/pm/board')
}

/** 项目列表 */
export function listProjects(params = {}) {
  return get('/pm/projects', params)
}

/** 项目详情（含 8 阶段工期计划表） */
export function getProject(id) {
  return get(`/pm/projects/${id}`)
}

export function createProject(payload) {
  return post('/pm/projects', payload)
}

export function updateProject(id, payload) {
  return put(`/pm/projects/${id}`, payload)
}

/** 删除项目（仅管理员；级联删除参考表副本） */
export function deleteProject(id) {
  return del(`/pm/projects/${id}`)
}

/** 批量保存阶段表 */
export function saveProjectStages(id, stages) {
  return put(`/pm/projects/${id}/stages`, stages)
}

/** 按标准模板重置阶段表 */
export function resetProjectStages(id) {
  return post(`/pm/projects/${id}/stages/reset`)
}

/** 按模板重置该项目三张参考表副本（工序/管理点/单据） */
export function resetProjectCopies(id) {
  return post(`/pm/projects/${id}/copies/reset`)
}

// ---------------------------------------------------------------------------
// 施工实施步骤明细
// ---------------------------------------------------------------------------
/** @param {number} [projectId] 不传 = 标准模板（仅管理员） */
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

/** 工序状态变更历史（按时间倒序） */
export function listPmProcessLogs(id) {
  return get(`/pm/processes/${id}/logs`)
}

// ---------------------------------------------------------------------------
// 预算决算管理点 / 配套单据
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
