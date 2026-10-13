/**
 * 供货商侧路由片段（供基座 router/index.js 合并，task-1 负责路由表）
 * ---------------------------------------------------------------------------
 * 供货商不显示左侧导航（router/menu.js 注释），所以建议把这两条路由挂在
 * **不带 AdminLayout 的空布局**下（页面自带 SupplierAppBar）。
 *
 * 用法（基座 router/index.js）：
 *   import { supplierRoutes } from '@/views/supplier/routes'
 *   ...routes: [ ..., ...supplierRoutes ]
 *
 * 路径与 stores/user.js 的 HOME_BY_ROLE.supplier = '/supplier/quotes' 对齐。
 */
export const supplierRoutes = [
  {
    path: '/supplier/quotes',
    name: 'supplier-quote-list',
    component: () => import('./QuoteList.vue'),
    meta: { title: '待报价', roles: ['supplier'] },
  },
  {
    path: '/supplier/quotes/:id',
    name: 'supplier-quote-fill',
    component: () => import('./QuoteFill.vue'),
    // 显式映射成 QuoteFill 声明的 rfqId，避免未声明的 id 落到根元素属性上
    props: (route) => ({ rfqId: route.params.id }),
    meta: { title: '填写报价', roles: ['supplier'] },
  },
]

export default supplierRoutes
