/**
 * 项目管理接口（CH-002，前缀 /api/pm）
 * ---------------------------------------------------------------------------
 * 与报价模块**完全独立**：不引用 rfq 的任何数据，后期如需关联再单独改造。
 * 返回结构见 backend/app/schemas.py 的 Pm* 模型。
 * 权限：我方内部账号（admin/buyer）；供货商访问返回 40300。
 */
import { get, post, put, del } from './request'

/** 看板汇总：summary / stage_distribution / projects / upcoming */
export function getPmBoard() {
  return get('/pm/board')
}

/** 项目列表（可按关键字/阶段/状态过滤） */
export function listProjects(params = {}) {
  return get('/pm/projects', params)
}

/** 项目详情（含 8 阶段工期计划表） */
export function getProject(id) {
  return get(`/pm/projects/${id}`)
}

/** 新建项目（后端自动生成 8 阶段模板） */
export function createProject(payload) {
  return post('/pm/projects', payload)
}

/** 更新项目基本信息 */
export function updateProject(id, payload) {
  return put(`/pm/projects/${id}`, payload)
}

/** 删除项目（仅管理员） */
export function deleteProject(id) {
  return del(`/pm/projects/${id}`)
}

/** 批量保存阶段表（整表覆盖，后端按 seq 排序落库） */
export function saveProjectStages(id, stages) {
  return put(`/pm/projects/${id}/stages`, stages)
}

/** 按标准 8 阶段模板重置阶段表 */
export function resetProjectStages(id) {
  return post(`/pm/projects/${id}/stages/reset`)
}

/** 施工实施步骤明细（全局参考表） */
export function listPmProcesses() {
  return get('/pm/processes')
}

/** 修改单条工序 */
export function updatePmProcess(id, payload) {
  return put(`/pm/processes/${id}`, payload)
}

/** 预算决算管理点（全局参考表） */
export function listPmCostPoints() {
  return get('/pm/cost-points')
}

/** 修改单条管理点 */
export function updatePmCostPoint(id, payload) {
  return put(`/pm/cost-points/${id}`, payload)
}

/** 预算决算配套单据（全局参考表） */
export function listPmDocuments() {
  return get('/pm/documents')
}

/** 修改单张单据 */
export function updatePmDocument(id, payload) {
  return put(`/pm/documents/${id}`, payload)
}
