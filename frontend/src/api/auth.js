/**
 * 认证接口（PRD 7.1）
 * 返回值为统一响应的 data 部分；失败 reject ApiError。
 */
import { get, post } from './request'

/**
 * 登录
 * @param {{username: string, password: string}} data
 * @returns {Promise<{token: string, token_type: string, user: object}>}
 */
export function login(data) {
  return post('/auth/login', data, { silent: true, skipAuth: true })
}

/** 退出（JWT 无状态，服务端仅记日志；前端必须自行清理本地 token） */
export function logout() {
  return post('/auth/logout', null, { silent: true })
}

/** 当前用户信息（用于刷新 must_change_password 等） */
export function fetchMe() {
  return get('/auth/me', null, { silent: true })
}

/**
 * 修改自己的密码
 * @param {{old_password: string, new_password: string}} data
 */
export function changePassword(data) {
  return post('/auth/change-password', data, { silent: true })
}
