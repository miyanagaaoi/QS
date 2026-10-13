/**
 * 用户与登录态（Pinia）
 * ---------------------------------------------------------------------------
 * 负责：token / 当前用户 / 角色 / supplier_id / must_change_password / 菜单过滤。
 * 持久化：token 存 localStorage（xj_token），用户信息存 xj_user（用于刷新后立即渲染，
 * 真实有效性由 /api/auth/me 校验，见 ensureProfile）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'
import { CODE, TOKEN_KEY, USER_KEY } from '@/api/request'
import { filterMenusByRole, resolveHome } from '@/router/menu'

/** 角色中文名（设计稿 / PRD 用词一致） */
export const ROLE_LABELS = Object.freeze({
  admin: '管理员',
  buyer: '采购员',
  supplier: '供货商',
})

function safeGet(key) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key, value) {
  try {
    if (value === null || value === undefined) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下静默失败：仅影响刷新后的免登录，不影响本次会话 */
  }
}

function readStoredUser() {
  const raw = safeGet(USER_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export const useUserStore = defineStore('user', () => {
  // —— 状态 ——
  const token = ref(safeGet(TOKEN_KEY) || '')
  const user = ref(readStoredUser())
  /** /auth/me 是否已校验过（避免每次路由跳转都请求） */
  const profileLoaded = ref(false)
  let profilePromise = null

  // —— 计算属性 ——
  const isLoggedIn = computed(() => Boolean(token.value))
  const role = computed(() => user.value?.role || '')
  const roleLabel = computed(() => ROLE_LABELS[role.value] || '')
  const username = computed(() => user.value?.username || '')
  const realName = computed(() => user.value?.real_name || '')
  const displayName = computed(() => realName.value || username.value)
  const avatarText = computed(() => (displayName.value || '?').trim().slice(0, 1))
  const supplierId = computed(() => user.value?.supplier_id ?? null)
  const supplierName = computed(() => user.value?.supplier_name || '')
  const mustChangePassword = computed(() => Boolean(user.value?.must_change_password))
  const isAdmin = computed(() => role.value === 'admin')
  const isBuyer = computed(() => role.value === 'buyer')
  const isSupplier = computed(() => role.value === 'supplier')
  /** 内部人员（管理员 / 采购员），用于布局与守卫判断 */
  const isInternal = computed(() => isAdmin.value || isBuyer.value)
  const menus = computed(() => filterMenusByRole(role.value))
  const homePath = computed(() => resolveHome(role.value))

  // —— 内部写入 ——
  function persist() {
    safeSet(TOKEN_KEY, token.value || null)
    safeSet(USER_KEY, user.value ? JSON.stringify(user.value) : null)
  }

  function setUser(next) {
    user.value = next ? { ...next } : null
    persist()
  }

  function setSession(payload) {
    token.value = payload?.token || ''
    user.value = payload?.user ? { ...payload.user } : null
    profileLoaded.value = true
    profilePromise = null
    persist()
  }

  function clearAuth() {
    token.value = ''
    user.value = null
    profileLoaded.value = false
    profilePromise = null
    persist()
  }

  // —— 行为 ——
  /** 登录：成功后写入 token 与用户信息，返回原始 data（含 user） */
  async function login(credentials) {
    const data = await authApi.login({
      username: String(credentials?.username || '').trim(),
      password: String(credentials?.password || ''),
    })
    setSession(data)
    return data
  }

  /** 拉取 /auth/me 刷新用户信息与 must_change_password */
  async function fetchProfile() {
    const data = await authApi.fetchMe()
    setUser(data)
    profileLoaded.value = true
    return data
  }

  /**
   * 保证用户信息是最新的（每个会话只真正请求一次）。
   * 若 token 已失效，request.js 会触发 onUnauthorized 清理登录态，这里继续抛错即可。
   */
  function ensureProfile() {
    if (!token.value) return Promise.resolve(null)
    if (profileLoaded.value && user.value) return Promise.resolve(user.value)
    if (!profilePromise) {
      profilePromise = fetchProfile().catch((error) => {
        profilePromise = null
        // 40100 / 40101 之外（如网络异常）保留本地缓存，避免离线时被踢出
        if (error?.code === CODE.UNAUTHORIZED) clearAuth()
        throw error
      })
    }
    return profilePromise
  }

  /** 修改自己的密码；成功后取消强制改密标记 */
  async function changePassword(payload) {
    await authApi.changePassword({
      old_password: String(payload?.old_password || ''),
      new_password: String(payload?.new_password || ''),
    })
    if (user.value) setUser({ ...user.value, must_change_password: false })
    return true
  }

  /** 后端返回 40101 时标记（由 main.js 的 authHandler 调用） */
  function markMustChangePassword() {
    if (user.value && !user.value.must_change_password) {
      setUser({ ...user.value, must_change_password: true })
    } else if (!user.value) {
      // 极端情况：本地无用户信息，仅记录标记位，等 /auth/me 回来覆盖
      user.value = { must_change_password: true }
      persist()
    }
  }

  /** 退出登录：先尽力调用后端（记日志），再无条件清本地 */
  async function logout() {
    try {
      if (token.value) await authApi.logout()
    } catch {
      /* 忽略：本地登出优先 */
    }
    clearAuth()
  }

  return {
    // 状态
    token,
    user,
    profileLoaded,
    // 计算属性
    isLoggedIn,
    role,
    roleLabel,
    username,
    realName,
    displayName,
    avatarText,
    supplierId,
    supplierName,
    mustChangePassword,
    isAdmin,
    isBuyer,
    isSupplier,
    isInternal,
    menus,
    homePath,
    // 方法
    login,
    logout,
    fetchProfile,
    ensureProfile,
    changePassword,
    markMustChangePassword,
    clearAuth,
    setUser,
  }
})
