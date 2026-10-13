/**
 * 导航菜单定义（PRD 9.3 前端导航结构）
 * ---------------------------------------------------------------------------
 * 纯数据模块，禁止引入 store / 组件，避免与 stores/user.js 形成循环依赖。
 * 菜单按角色过滤由 stores/user.js 的 menus 计算属性完成（双层守卫的第一层，
 * 第二层是路由 meta.roles + 后端接口鉴权，以后端为准）。
 */

export const MENU_TREE = [
  {
    key: 'purchase',
    title: '采购管理',
    icon: 'ShoppingCart',
    roles: ['admin', 'buyer'],
    children: [
      { key: 'rfq', title: '报价单', path: '/purchase/rfq', icon: 'Tickets' },
      { key: 'rfq-report', title: '报价单统计报表', path: '/purchase/report', icon: 'TrendCharts' },
    ],
  },
  {
    key: 'system',
    title: '系统管理',
    icon: 'Setting',
    roles: ['admin'],
    children: [
      { key: 'account', title: '账号管理', path: '/system/account', icon: 'User' },
      // 需求方最终结构（2026-10 更正）：「字典维护」恢复为独立菜单项（独立页面，页内三页签）
      { key: 'dict', title: '字典维护', path: '/system/dict', icon: 'Collection' },
      { key: 'audit-log', title: '操作日志', path: '/system/audit-log', icon: 'List' },
    ],
  },
]

/** 各角色登录后的默认落地页 */
export const HOME_BY_ROLE = Object.freeze({
  admin: '/purchase/rfq',
  buyer: '/purchase/rfq',
  supplier: '/supplier/quotes',
})

export function resolveHome(role) {
  return HOME_BY_ROLE[role] || '/login'
}

/**
 * 按角色过滤菜单（采购员看不到「系统管理」整组；供货商不显示左侧导航）
 * @param {string} role admin | buyer | supplier
 */
export function filterMenusByRole(role) {
  if (!role) return []
  return MENU_TREE.filter((group) => !group.roles || group.roles.includes(role))
    .map((group) => ({
      ...group,
      children: (group.children || []).filter((item) => !item.roles || item.roles.includes(role)),
    }))
    .filter((group) => group.children.length > 0)
}

/**
 * 计算菜单高亮项：取最长匹配前缀
 * 例：/purchase/rfq/new、/purchase/rfq/12 都高亮 /purchase/rfq
 */
export function resolveActiveMenu(path) {
  const items = MENU_TREE.flatMap((group) => group.children || [])
  let matched = ''
  items.forEach((item) => {
    if (path === item.path || path.startsWith(`${item.path}/`)) {
      if (item.path.length > matched.length) matched = item.path
    }
  })
  return matched || path
}
