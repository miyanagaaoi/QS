# 前端基座对外接口契约（task-1 · fe-base）

> 面向 `views/purchase`、`views/supplier`、`views/system` 的对接方。
> 基座代码：`src/main.js`、`src/App.vue`、`src/api/*`、`src/stores/*`、`src/router/*`、
> `src/layouts/*`、`src/components/*`、`src/composables/*`、`src/styles/*`、`public/*`。

## 1. 请求层 `@/api/request`

```js
import { get, post, put, patch, del, upload, download, request, requestRaw, ApiError, CODE } from '@/api/request'
```

| 导出 | 说明 |
|---|---|
| `get(url, params?, config?)` | GET，返回**统一响应的 `data` 部分** |
| `post/put/patch(url, data?, config?)` | 同上 |
| `del(url, config?)` | DELETE |
| `upload(url, formData, { onProgress })` | multipart，`onProgress(0~100)` |
| `download(url, { method, params, data, filename })` | 带 token 取 Blob 并触发保存；返回 `{ filename }` |
| `request(config)` / `requestRaw(config)` | 底层；`requestRaw` 返回完整信封 `{code,message,data}` |
| `ApiError` | 失败时 reject 的错误类型：`code / message / data / status`，含 `isUnauthorized` 等便捷判断 |
| `CODE` | `{ OK:0, PARAM:40001, UNAUTHORIZED:40100, MUST_CHANGE_PASSWORD:40101, FORBIDDEN:40300, QUOTE_CLOSED:40301, NOT_FOUND:40400, CONFLICT:40900, SERVER:50000 }` |

约定与坑：

- **成功只拿 data**：`const page = await get('/rfqs', { page: 1 })`，不要再读 `res.code`。
- **失败一定 reject**，默认自动 Toast；页面要自己处理就传 `{ silent: true }`（登录/改密接口已内置 silent）。
- `code=40001` 时字段级错误在 `error.data.errors`（`ApiError.fieldErrors`）。
- `40100`：基座自动 **清 token + 跳 `/login`**（含同行 request 的后续请求）；页面**不要**重复跳转。
  后端"改密/重置密码"会让旧 token 立即失效，所以 40100 会出现在会话中途。
- `40101`：基座自动跳 `/change-password`。注意 `/api/auth/me` 也在拦截范围内（未改密账号调业务接口会得到 40101）。
- `40300`：自动 Toast「无权访问该功能」并通知 `onForbidden`。
- 金额/数量后端是**字符串**（Decimal），展示用 `useFormat`，提交时**原样透传字符串**。
- 域接口薄封装：`@/api/auth.js`、`@/api/rfq.js`、`@/api/supplier.js`、`@/api/report.js`、`@/api/admin.js`（参数透传，字段以 `backend/app/schemas.py` 为准）。

## 2. 登录态 `@/stores/user`（Pinia）

```js
import { useUserStore, ROLE_LABELS } from '@/stores/user'
const u = useUserStore()
```

- 状态：`token`、`user`、`profileLoaded`
- 计算：`isLoggedIn`、`role`(`admin|buyer|supplier`)、`roleLabel`、`username`、`realName`、`displayName`、
  `avatarText`、`supplierId`、`supplierName`、`mustChangePassword`、`isAdmin`、`isBuyer`、`isSupplier`、`isInternal`、
  `menus`（已按角色过滤）、`homePath`
- 方法：`login({username,password})`、`logout()`、`fetchProfile()`、`ensureProfile()`、`changePassword({old_password,new_password})`、
  `markMustChangePassword()`、`clearAuth()`、`setUser(user)`
- localStorage：`xj_token`、`xj_user`

> 改密成功后旧 token 立即失效：`ChangePassword.vue` 的流程是「成功后 `clearAuth()` + 回登录页」，
> 其它页面若自建改密入口，请沿用同一流程。

## 3. 路由与守卫 `@/router`

路由表见 `src/router/index.js`（全部懒加载）。页面只需 `useRoute()/useRouter()`，不要自建路由表。

- `meta.title`：顶部标题、面包屑与 `document.title`
- `meta.roles`：`['admin','buyer']` 或 `['admin']` 或 `['supplier']`
- `meta.public`：无需登录
- `meta.back`：手机端显示返回箭头
- `meta.selfHeader`：页面自带顶栏时置 `true`，布局不再渲染顶栏（供货商两页已用，避免双头部）

守卫行为：未登录 → `/login?redirect=`；`must_change_password` → 强制 `/change-password`；
`/purchase/*`、`/system/*` 对供货商一律拦截并回其首页；角色不匹配 → `/403`。

菜单定义在 `src/router/menu.js`（`MENU_TREE` / `filterMenusByRole` / `resolveHome` / `resolveActiveMenu`）。

## 4. 断点：唯一定义 + JS 常量

- SCSS：`@use '@/styles/breakpoints' as bp;` → `bp.mobile`(<768) / `bp.tablet`(768~1199) / `bp.desktop`(≥1200) /
  `bp.tablet-up`(≥768) / `bp.desktop-up` / `bp.touch` / `bp.landscape` / `bp.reduce-motion`
- JS：`import { useBreakpoint } from '@/composables/useBreakpoint'`
  → `{ width, isMobile, isTablet, isDesktop, isTabletUp, isLandscape, breakpoint, breakpoints, matches(min) }`（均为响应式）
- 断点数值只在 `src/styles/breakpoints.scss` 写一次；`vite.config.js` 解析后注入 `__XJ_BREAKPOINTS__`。
  **业务组件禁止硬编码断点像素，也禁止 UA 嗅探。**
- 背景滚动锁定：`import { useBodyScrollLock } from '@/composables/useBodyScrollLock'`（`useBodyScrollLock(ref)`，计数式、自动补偿滚动条）

## 5. 通用组件（`src/components`，已全局自动注册，也可显式 import）

### DataTable.vue（桌面表格 ↔ 手机卡片）

Props：`data`、`columns`、`cardFields`、`cardTitle`、`rowKey`(默认 `'id'`)、`loading`、`emptyText`、`title`、
`selectable`、`indexColumn`、`actionsWidth`(默认 170)、`height`、`maxHeight`、`pagination`(`{page,pageSize,total}`)、`mode`(`auto|table|card`)

`columns[]`：`{ prop, label, slot, width, minWidth, align, sortable, fixed, formatter(row,col), num, hiddenOn:['tablet'|'desktop'] }`
`cardFields[]`：`{ label, prop, slot, formatter(row,field), num }`；不传时取 `columns` 前 5 个可显示列

Slots：`toolbar`、`actions="{row,index}"`、`card="{row,index}"`、`card-title`、`card-extra`、`card-<prop>`、`empty`、以及同名 `<prop>` 单元格插槽
Emits：`selection-change`、`sort-change`、`row-click`、`page-change({page,pageSize})`、`update:page`、`update:pageSize`
方法（ref）：`clearSelection()`

### 其它

- `FilterDrawer.vue`：props `title`/`activeCount`/`inline`/`size`/`modelValue`/`triggerText`/`loading`；slots `default`/`actions`/`trigger-extra`；emits `search`/`reset`/`update:modelValue`。手机自动变「筛选」按钮 + 底部弹层。
- `StickyBar.vue`：props `mode`(`auto|fixed|inline`)、`safeArea`、`bordered`；slots `default`(左信息)、`actions`(右按钮)。手机自动吸底 + `env(safe-area-inset-bottom)`。
- `StatusBadge.vue`：props `status`/`label`/`tone`/`filled`/`total`/`dot`/`size`。**徽标必带文字**（无障碍硬约束）。
- `status.js`：`STATUS_META`、`TONE_CLASS`、`statusMeta/statusLabel/statusTone/assignProgressText`（列定义可直接引用）。
- `AppStatePage.vue`：404/403 状态页（路由兜底使用）。

## 6. 格式化 `@/composables/useFormat`

`formatMoney` `formatAmount` `formatQty` `formatTaxRate` `formatPercent` `formatDiffRate` `formatDate`
`formatDateTime` `formatDateTimeShort` `toDateTimeInputValue` `formatRemaining` `secondsUntil`
`isDeadlineNear` `formatFileSize` `parseDateTime`，以及 `useFormat()` 组合式用法。

`parseDateTime` 手写解析 `YYYY-MM-DD[T ]HH:mm:ss`，兼容 iOS Safari。
⚠️ 供货商侧实测：`deadline` 是 **UTC naive** 字符串，展示/倒计时请以 `remaining_seconds` 为基准（见 `views/supplier/quoteModel.js` 的结论）。

## 7. 样式规范

- 令牌：`@use '@/styles/variables' as v;` → `v.$brand-800`(#0E4F4A) 等，全部来自 `doc/design/01-design-system.html`。
  **禁止自创色值、紫蓝渐变、玻璃拟态**；最低价只用 `v.$best-bg/$best-line/$best-ink`。
- 全局样式入口 `src/styles/index.scss`（基础样式 + 工具类 `.num`/`.xj-hscroll`/`.u-sr-only`/`.xj-only-mobile`）
  与 `src/styles/element-overrides.scss`（Element Plus 主题覆写，用 `:root:root` 提升特异性）。
- Element Plus **按需引入**（`unplugin-vue-components` + `unplugin-auto-import`，`vite.config.js`）：
  模板里的 `<el-xxx>` 自动引入并带样式；若**手写** `import { ElMessage } from 'element-plus'`，
  消息组件样式已由 `src/api/request.js` 全局引入，其它函数式组件（ElMessageBox 等）请在页面里补
  `import 'element-plus/es/components/message-box/style/css'`，或改为不写 import 交给自动引入。
- 禁止引入 `postcss-px-to-viewport` 之类 px→vw 插件（PRD 9.1）。
- 手机端输入框 ≥16px 由 `element-overrides.scss` 统一保证（`html body .el-input .el-input__inner{font-size:1rem}`），
  `index.html` 的 viewport **不含** `maximum-scale=1`。
