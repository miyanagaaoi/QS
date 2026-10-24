/**
 * 路由与角色守卫（PRD 9.3 / FR-RWD-01）
 * ---------------------------------------------------------------------------
 * 守卫双层的第一层（第二层是后端接口鉴权，以后端为准）：
 *   1. 未登录 → /login（带 redirect）
 *   2. must_change_password=true → 强制 /change-password（除该页外一律拦截，对应 40101）
 *   3. meta.roles 角色校验 + 供货商禁止访问 /purchase/* 与 /system/*
 *   4. 已登录访问 /login → 按角色落到各自首页
 *
 * 视图组件一律懒加载（() => import(...)），保证首屏只加载当前路由所需代码。
 * 菜单高亮与角色过滤见 router/menu.js 与 stores/user.js。
 */
import { createRouter, createWebHistory } from 'vue-router'

import { CODE } from '@/api/request'
import { resolveHome } from '@/router/menu'
import { useUserStore } from '@/stores/user'

const AdminLayout = () => import('@/layouts/AdminLayout.vue')
const SupplierLayout = () => import('@/layouts/SupplierLayout.vue')
const AppStatePage = () => import('@/components/AppStatePage.vue')

/** 内部人员路径前缀：供货商一律不得进入 */
const INTERNAL_PREFIXES = ['/purchase', '/system']

const INTERNAL_ROLES = ['admin', 'buyer']

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePassword.vue'),
    meta: { title: '修改密码', allowMustChange: true },
  },

  // —— 我方侧：采购管理 ——
  {
    path: '/purchase',
    component: AdminLayout,
    meta: { roles: INTERNAL_ROLES },
    redirect: '/purchase/rfq',
    children: [
      {
        path: 'rfq',
        name: 'rfq-list',
        component: () => import('@/views/purchase/RfqList.vue'),
        meta: { title: '报价单', roles: INTERNAL_ROLES },
      },
      // 注意：静态段 new 必须排在 :id 之前，否则会被当成 id
      {
        path: 'rfq/new',
        name: 'rfq-create',
        component: () => import('@/views/purchase/RfqEdit.vue'),
        meta: { title: '新建询价单', roles: INTERNAL_ROLES, back: true },
      },
      {
        path: 'rfq/:id/edit',
        name: 'rfq-edit',
        component: () => import('@/views/purchase/RfqEdit.vue'),
        meta: { title: '编辑询价单', roles: INTERNAL_ROLES, back: true },
      },
      {
        path: 'rfq/:id',
        name: 'rfq-progress',
        component: () => import('@/views/purchase/RfqProgress.vue'),
        meta: { title: '报价进度', roles: INTERNAL_ROLES, back: true },
      },
      {
        path: 'rfq/:id/report',
        name: 'rfq-report-detail',
        component: () => import('@/views/purchase/RfqReport.vue'),
        meta: { title: '报价单统计报表', roles: INTERNAL_ROLES, back: true },
      },
      {
        path: 'report',
        name: 'rfq-report',
        component: () => import('@/views/purchase/RfqReport.vue'),
        meta: { title: '报价单统计报表', roles: INTERNAL_ROLES },
      },
    ],
  },

  // —— 项目管理（CH-002）：独立模块，与报价数据无关联 ——
  {
    path: '/pm',
    component: AdminLayout,
    meta: { roles: ['admin', 'buyer'] },
    children: [
      {
        path: '',
        name: 'pm-board',
        component: () => import('@/views/pm/PmBoard.vue'),
        meta: { title: '项目管理', roles: ['admin', 'buyer'] },
      },
      {
        path: 'projects/:id',
        name: 'pm-project-detail',
        component: () => import('@/views/pm/PmProjectDetail.vue'),
        meta: { title: '工期计划表', roles: ['admin', 'buyer'] },
      },
      {
        path: 'processes',
        name: 'pm-processes',
        component: () => import('@/views/pm/PmProcesses.vue'),
        meta: { title: '施工实施步骤明细', roles: ['admin', 'buyer'] },
      },
      {
        path: 'cost-points',
        name: 'pm-cost-points',
        component: () => import('@/views/pm/PmCostPoints.vue'),
        meta: { title: '预算决算管理点', roles: ['admin', 'buyer'] },
      },
      {
        path: 'documents',
        name: 'pm-documents',
        component: () => import('@/views/pm/PmDocuments.vue'),
        meta: { title: '预算决算配套单据', roles: ['admin', 'buyer'] },
      },
    ],
  },

  // —— 我方侧：系统管理（仅管理员，采购员菜单也不显示）——
  {
    path: '/system',
    component: AdminLayout,
    meta: { roles: ['admin'] },
    redirect: '/system/account',
    children: [
      {
        path: 'account',
        name: 'system-account',
        component: () => import('@/views/system/AccountList.vue'),
        meta: { title: '账号管理', roles: ['admin'] },
      },
      {
        // 需求方最终结构（2026-10 更正）：「字典维护」恢复为独立页面，页内三页签
        // （计量单位 / 税率 / 供货商档案），页签状态走 ?tab=unit|tax|supplier
        path: 'dict',
        name: 'system-dict',
        component: () => import('@/views/system/DictList.vue'),
        meta: { title: '字典维护', roles: ['admin'] },
      },
      {
        path: 'audit-log',
        name: 'system-audit-log',
        component: () => import('@/views/system/AuditLog.vue'),
        meta: { title: '操作日志', roles: ['admin'] },
      },
    ],
  },

  // —— 供货商侧（手机优先）——
  {
    path: '/supplier',
    component: SupplierLayout,
    meta: { roles: ['supplier'] },
    redirect: '/supplier/quotes',
    children: [
      {
        path: 'quotes',
        name: 'supplier-quote-list',
        component: () => import('@/views/supplier/QuoteList.vue'),
        // selfHeader：页面自带设计稿 03 的暗色 appbar，布局不再重复渲染顶栏
        meta: { title: '待报价', roles: ['supplier'], selfHeader: true },
      },
      {
        path: 'quotes/:id',
        name: 'supplier-quote-fill',
        component: () => import('@/views/supplier/QuoteFill.vue'),
        // 显式映射为页面声明的 rfqId，避免未声明的 id 落到根元素属性上
        props: (route) => ({ rfqId: route.params.id }),
        meta: { title: '报价填报', roles: ['supplier'], back: true, selfHeader: true },
      },
    ],
  },

  // —— 首页：按角色分发 ——
  {
    path: '/',
    name: 'home',
    redirect: () => resolveHome(useUserStore().role),
  },

  {
    path: '/403',
    name: 'forbidden',
    component: AppStatePage,
    props: { status: '403', title: '无权访问', desc: '当前账号没有访问该页面的权限，请用有权限的账号登录。' },
    meta: { title: '无权访问' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: AppStatePage,
    props: { status: '404', title: '页面不存在', desc: '链接可能已失效，或该页面已被移除。' },
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL || '/'),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

function isInternalPath(path) {
  return INTERNAL_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`))
}

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  // 公开页
  if (to.meta.public) {
    if (to.name === 'login' && userStore.isLoggedIn) return resolveHome(userStore.role)
    return true
  }

  // 未登录
  if (!userStore.isLoggedIn) {
    const redirect = to.fullPath && to.fullPath !== '/' ? to.fullPath : undefined
    return { path: '/login', query: redirect ? { redirect } : undefined }
  }

  // 校验 token 有效性并刷新 must_change_password（每个会话只请求一次 /auth/me）
  try {
    await userStore.ensureProfile()
  } catch (error) {
    if (error?.code === CODE.UNAUTHORIZED) {
      const redirect = to.fullPath && to.fullPath !== '/' ? to.fullPath : undefined
      return { path: '/login', query: redirect ? { redirect } : undefined }
    }
    // 后端对 /auth/me 也返回 40101（未改密的账号不得调用业务接口，PRD TC-02）
    if (error?.code === CODE.MUST_CHANGE_PASSWORD) {
      return { path: '/change-password' }
    }
    // 网络异常 / 服务端 5xx：不阻断，用本地缓存的用户信息继续（避免内网抖动时无法操作）
  }

  if (!userStore.isLoggedIn) return { path: '/login' }

  // 强制修改初始密码（40101）：除改密页外一律拦截
  if (userStore.mustChangePassword && !to.meta.allowMustChange) {
    return { path: '/change-password' }
  }

  const role = userStore.role

  // 供货商禁止访问我方侧路径（即使 meta 缺失也拦截）
  if (role === 'supplier' && isInternalPath(to.path)) {
    return { path: resolveHome('supplier'), query: { denied: to.fullPath } }
  }

  // 角色不匹配
  const roles = to.meta.roles
  if (Array.isArray(roles) && roles.length && !roles.includes(role)) {
    return { path: '/403' }
  }

  return true
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · 采购与项目管理平台` : '采购与项目管理平台'
})

export default router
