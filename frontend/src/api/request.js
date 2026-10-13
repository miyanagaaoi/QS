/**
 * axios 封装 —— 全站唯一的 HTTP 出口（PRD 7.6 统一响应与错误码）
 * ---------------------------------------------------------------------------
 * 约定：
 *   1. 后端统一返回 { code, message, data }，HTTP 状态码与业务码并存
 *      （401/400/403 等由 FastAPI 抛出，body 里仍带 code）。
 *   2. 本封装把成功响应的 data 直接返回：
 *        const page = await get('/rfqs', { page: 1 })   // => data
 *      业务失败一律 reject 一个 ApiError（含 code / message / data / status）。
 *   3. 需要在页面里自行处理错误（如 40001 字段级提示），传 { silent: true } 关闭默认 Toast。
 *   4. token 直接从 localStorage 读，避免 request.js ↔ store ↔ router 循环依赖；
 *      登录态失效后的跳转由 main.js 注入的 authHandlers 负责。
 *
 * 副作用（自动执行，无需业务代码处理）：
 *   code=40100 → 清登录态并跳 /login
 *   code=40101 → 强制跳 /change-password
 *   code=40300 → Toast「无权访问」并通知 onForbidden
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
// 显式引入组件样式：本项目按需引入 Element Plus（无全局 css），
// 手写 import 的组件不会自动带样式，必须自己引。
import 'element-plus/es/components/message/style/css'

export const API_BASE = import.meta.env.VITE_API_BASE || '/api'

/** localStorage 键名（stores/user.js 与本文件共用） */
export const TOKEN_KEY = 'xj_token'
export const USER_KEY = 'xj_user'

/** 业务错误码（PRD 7.6） */
export const CODE = Object.freeze({
  OK: 0,
  PARAM: 40001, // 参数校验失败 → 定位到具体字段
  UNAUTHORIZED: 40100, // 未登录 / Token 失效 → 跳登录页
  MUST_CHANGE_PASSWORD: 40101, // 需修改初始密码 → 强制跳改密页
  FORBIDDEN: 40300, // 无权限
  QUOTE_CLOSED: 40301, // 报价已截止 → 页面置为只读
  NOT_FOUND: 40400, // 资源不存在
  CONFLICT: 40900, // 业务冲突
  SERVER: 50000, // 服务端异常
})

export class ApiError extends Error {
  constructor(message, code = CODE.SERVER, data = null, status = 0) {
    super(message || '请求失败')
    this.name = 'ApiError'
    this.code = code
    this.data = data
    this.status = status
  }

  get isUnauthorized() {
    return this.code === CODE.UNAUTHORIZED
  }

  get isMustChangePassword() {
    return this.code === CODE.MUST_CHANGE_PASSWORD
  }

  get isForbidden() {
    return this.code === CODE.FORBIDDEN
  }

  get isQuoteClosed() {
    return this.code === CODE.QUOTE_CLOSED
  }

  get isConflict() {
    return this.code === CODE.CONFLICT
  }

  /** 参数校验失败时的字段级错误（后端放在 data.errors） */
  get fieldErrors() {
    return Array.isArray(this.data?.errors) ? this.data.errors : []
  }
}

// ---------------------------------------------------------------------------
// localStorage 安全访问（隐私模式 / 禁用存储时不抛异常）
// ---------------------------------------------------------------------------
export function readToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

// ---------------------------------------------------------------------------
// 认证副作用钩子：main.js 注入（内部含 location 兜底）
// ---------------------------------------------------------------------------
const authHandlers = {
  onUnauthorized: null,
  onMustChangePassword: null,
  onForbidden: null,
}

export function setAuthHandlers(handlers = {}) {
  Object.assign(authHandlers, handlers)
}

function fallbackRedirect(path) {
  try {
    if (window.location.pathname !== path) window.location.replace(path)
  } catch {
    /* 忽略 */
  }
}

// ---------------------------------------------------------------------------
// 实例
// ---------------------------------------------------------------------------
export const http = axios.create({
  baseURL: API_BASE,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  if (!config.skipAuth) {
    const token = readToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

const recentToasts = new Map()

/** 同一文案 1.5s 内只提示一次，避免列表页并发请求刷屏 */
function toastOnce(message, type = 'error') {
  const text = String(message || '').trim()
  if (!text) return
  const now = Date.now()
  const last = recentToasts.get(text) || 0
  if (now - last < 1500) return
  recentToasts.set(text, now)
  ElMessage({ message: text, type, duration: 2600, showClose: true })
}

/** 成功类提示（业务代码可直接复用） */
export function toastSuccess(message) {
  ElMessage({ message, type: 'success', duration: 2200 })
}

function normalizeError(error) {
  const status = error?.response?.status || 0
  const body = error?.response?.data
  let code = CODE.OK
  let message = ''
  let data = null

  if (body && typeof body === 'object' && 'code' in body) {
    code = Number(body.code) || CODE.OK
    message = body.message || ''
    data = body.data ?? null
  }

  if (!code) {
    if (status === 401) code = CODE.UNAUTHORIZED
    else if (status === 403) code = CODE.FORBIDDEN
    else if (status === 404) code = CODE.NOT_FOUND
    else if (status === 409) code = CODE.CONFLICT
    else if (status === 400) code = CODE.PARAM
    else if (status >= 500) code = CODE.SERVER
    else code = CODE.SERVER
  }

  if (!message) {
    if (error?.code === 'ECONNABORTED' || /timeout/i.test(error?.message || '')) {
      message = '请求超时，请检查网络后重试'
    } else if (!error?.response) {
      message = '网络异常，请检查网络后重试'
    } else {
      message = `请求失败（HTTP ${status}）`
    }
  }

  return new ApiError(message, code, data, status)
}

/** 统一处理认证类副作用 + 默认 Toast，然后 reject */
function settleError(error, config = {}) {
  const { code } = error

  if (code === CODE.UNAUTHORIZED) {
    if (authHandlers.onUnauthorized) authHandlers.onUnauthorized(error)
    else fallbackRedirect('/login')
  } else if (code === CODE.MUST_CHANGE_PASSWORD) {
    if (authHandlers.onMustChangePassword) authHandlers.onMustChangePassword(error)
    else fallbackRedirect('/change-password')
  } else if (code === CODE.FORBIDDEN) {
    if (!config.silent) toastOnce(error.message || '无权访问该功能')
    authHandlers.onForbidden?.(error)
  } else if (code === CODE.QUOTE_CLOSED) {
    if (!config.silent) toastOnce(error.message || '报价已截止', 'warning')
  } else if (!config.silent && code !== CODE.OK) {
    toastOnce(error.message)
  }

  return Promise.reject(error)
}

http.interceptors.response.use(
  (response) => {
    const config = response.config || {}
    // 二进制流（导出/下载）交给 download() 处理
    if (config.responseType === 'blob' || config.responseType === 'arraybuffer') return response

    const body = response.data
    // 非统一响应体（如网关返回 HTML）原样返回，避免误判
    if (!body || typeof body !== 'object' || !('code' in body)) return body

    if (body.code === CODE.OK) return config.__raw ? body : body.data

    const error = new ApiError(body.message || '请求失败', Number(body.code) || CODE.SERVER, body.data ?? null, response.status)
    return settleError(error, config)
  },
  (error) => {
    if (axios.isCancel?.(error) || error?.code === 'ERR_CANCELED') return Promise.reject(error)
    return settleError(normalizeError(error), error?.config || {})
  },
)

// ---------------------------------------------------------------------------
// 便捷方法（返回 data；失败 reject ApiError）
// ---------------------------------------------------------------------------
export function request(config) {
  return http.request(config)
}

/** 需要完整信封 { code, message, data } 时使用 */
export function requestRaw(config) {
  return http.request({ ...config, __raw: true })
}

export function get(url, params, config = {}) {
  return http.get(url, { params, ...config })
}

export function post(url, data, config = {}) {
  return http.post(url, data, config)
}

export function put(url, data, config = {}) {
  return http.put(url, data, config)
}

export function patch(url, data, config = {}) {
  return http.patch(url, data, config)
}

export function del(url, config = {}) {
  return http.delete(url, config)
}

/** 表单上传（Excel 导入等），onProgress 回调参数为 0~100 */
export function upload(url, formData, { onProgress, ...config } = {}) {
  return http.post(url, formData, {
    ...config,
    headers: { 'Content-Type': 'multipart/form-data', ...(config.headers || {}) },
    onUploadProgress: (event) => {
      if (!onProgress || !event.total) return
      onProgress(Math.round((event.loaded * 100) / event.total))
    },
  })
}

// ---------------------------------------------------------------------------
// 下载（导出 .xlsx / 附件）：带 token 请求 → Blob → 触发浏览器保存
// ---------------------------------------------------------------------------
function parseFilename(disposition) {
  if (!disposition) return ''
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      return utf8[1]
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : ''
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // 交给浏览器读完再释放
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

/**
 * 是否在微信内置浏览器中。
 * 微信 WebView 对 `a[download]` 支持不一致（iOS 微信通常直接无响应），
 * 因此导出类操作需要额外提示用户改用系统浏览器（PRD FR-RWD-28 / TC-61）。
 */
function isWeChatBrowser() {
  try {
    const ua = String(navigator.userAgent || '')
    return /MicroMessenger/i.test(ua)
  } catch {
    return false
  }
}

/** 微信内下载后的引导提示（频次限制，避免批量导出时刷屏） */
function warnWeChatDownload() {
  if (!isWeChatBrowser()) return
  const text = '已开始下载。微信内可能无法保存文件，若无反应请点右上角「···」选择「在浏览器打开」后重试。'
  const now = Date.now()
  const last = recentToasts.get(text) || 0
  if (now - last < 5000) return
  recentToasts.set(text, now)
  ElMessage({ message: text, type: 'warning', duration: 6000, showClose: true })
}

/**
 * 下载文件。后端异常时可能以 JSON 信封返回错误，这里会解析并抛出 ApiError。
 * @returns {Promise<{filename: string}>}
 */
export async function download(url, { method = 'get', params, data, filename, silent = false } = {}) {
  const response = await http.request({ url, method, params, data, responseType: 'blob', silent })
  const blob = response.data
  const contentType = response.headers?.['content-type'] || ''

  if (contentType.includes('application/json')) {
    let body = null
    try {
      body = JSON.parse(await blob.text())
    } catch {
      body = null
    }
    const error = new ApiError(body?.message || '下载失败', Number(body?.code ?? CODE.SERVER), body?.data ?? null, response.status)
    if (!silent) toastOnce(error.message)
    throw error
  }

  const name = filename || parseFilename(response.headers?.['content-disposition']) || 'download.xlsx'
  saveBlob(blob, name)
  if (!silent) warnWeChatDownload()
  return { filename: name }
}

export default http
