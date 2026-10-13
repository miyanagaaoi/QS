<script setup>
/**
 * AccountList — 系统管理 · 账号管理（PRD 5.4.1 / 5.4.2 / FR-RWD-14，设计稿 04-1、04-2）
 * ---------------------------------------------------------------------------
 * 三个页签：我方人员 / 供货商账号 / 供货商档案
 *
 * 必须遵守的业务约束：
 *  1. **账号无删除入口**（后端也没有删除接口），只可停用；页头与页脚均明示；
 *  2. 停用/降级**最后一个启用的管理员**时后端返回 409 / code=40900，
 *     前端必须把后端 message **原文**展示出来（而不是"操作失败"）——
 *     这里用「页内常驻红色提示条 + 弹窗」双呈现，原文完整保留；
 *  3. 重置密码成功后提示"该账号下次登录需修改密码"（后端 message 即此文案，原文展示）；
 *  4. 供货商账号支持"未首次登录"筛选（login_state=never）；
 *  5. 手机端：卡片列表 + 可查看/启停用/重置密码；批量导入入口隐藏并引导到电脑端。
 *
 * 数据形态：PageData<UserListItem> / PageData<SupplierOut>（backend/app/schemas.py）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import DataTable from '@/components/DataTable.vue'
import FilterDrawer from '@/components/FilterDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatDateTime, formatDateTimeShort } from '@/composables/useFormat'

import * as api from './adminApi'
import SupplierImport from './SupplierImport.vue'

defineOptions({ name: 'SystemAccountList' })

const { isMobile } = useBreakpoint()
const route = useRoute()
const router = useRouter()

// ---------------------------------------------------------------------------
// 页签：我方人员 / 供货商账号
// 需求方最终结构（2026-10 更正）：字典维护回到独立菜单与独立页面（页内三页签），
// 账号管理只保留这两个页签；供货商档案只在字典维护页维护（本页不再引用 SupplierArchivePanel）。
// 页签状态写进 URL query（?tab=internal|supplier），刷新/分享链接后停在原页签
// ---------------------------------------------------------------------------
const TABS = [
  { key: 'internal', label: '我方人员' },
  { key: 'supplier', label: '供货商账号' },
]
const TAB_KEYS = TABS.map((tab) => tab.key)

function normalizeTab(value) {
  const key = String(value || '')
  // 旧链接 ?tab=dict 会优雅退化成第一个页签
  return TAB_KEYS.includes(key) ? key : 'internal'
}

const activeTab = ref(normalizeTab(route.query.tab))

/** 把当前页签写回 URL（保留其它 query，如 new_account_for） */
function syncTabToUrl(key) {
  const query = { ...route.query, tab: key }
  // 离开供货商账号页签时清掉"预选档案"的一次性参数
  if (key !== 'supplier') delete query.new_account_for
  router.replace({ path: '/system/account', query }).catch(() => {})
}

/** 后端没有"账号数量统计"接口，用 page_size=1 读 meta.total（同时拿到启用/停用分项） */
const counts = reactive({
  internalOn: 0,
  internalOff: 0,
  supplierOn: 0,
  supplierOff: 0,
  archive: 0,
})
const internalTotal = computed(() => counts.internalOn + counts.internalOff)
const supplierTotal = computed(() => counts.supplierOn + counts.supplierOff)

async function loadCounts() {
  const safe = async (promise, pick) => {
    try {
      const data = await promise
      pick(Number(data?.meta?.total || 0))
    } catch {
      /* 计数失败不影响主流程 */
    }
  }
  await Promise.all([
    safe(api.listUsers({ page: 1, page_size: 1, status: 1 }), (n) => (counts.internalOn = n)),
    safe(api.listUsers({ page: 1, page_size: 1, status: 0 }), (n) => (counts.internalOff = n)),
    safe(api.listSupplierAccounts({ page: 1, page_size: 1, status: 1 }), (n) => (counts.supplierOn = n)),
    safe(api.listSupplierAccounts({ page: 1, page_size: 1, status: 0 }), (n) => (counts.supplierOff = n)),
    safe(api.listSuppliers({ page: 1, page_size: 1 }), (n) => (counts.archive = n)),
  ])
}

// ---------------------------------------------------------------------------
// 通用：后端原文错误提示（409 等）
// ---------------------------------------------------------------------------
/** 常驻展示的后端拒绝原因原文（如"系统至少需保留一个启用的管理员账号，无法停用……"） */
const blockingNotice = ref('')

async function showBackendReason(title, error, fallback) {
  const text = String(error?.message || '').trim() || fallback
  blockingNotice.value = text
  await ElMessageBox.alert(text, title, {
    type: 'error',
    confirmButtonText: '我知道了',
  }).catch(() => {})
}

// ---------------------------------------------------------------------------
// A. 我方人员
// ---------------------------------------------------------------------------
const internal = reactive({
  loading: false,
  rows: [],
  page: 1,
  pageSize: 20,
  total: 0,
  query: { keyword: '', role: '', status: '' },
})

const ROLE_OPTIONS = [
  { value: 'admin', label: '管理员' },
  { value: 'buyer', label: '采购员' },
]

const internalColumns = [
  { prop: 'username', label: '用户名', width: 150, num: true },
  { prop: 'real_name', label: '姓名', width: 120 },
  { prop: 'role', label: '角色', width: 110 },
  { prop: 'status', label: '状态', width: 120 },
  { prop: 'last_login_at', label: '最后登录时间', width: 165, num: true, hiddenOn: ['tablet'] },
  { prop: 'created_at', label: '创建时间', width: 165, num: true, hiddenOn: ['tablet'] },
]

// 手机卡片：状态只以标题右侧徽标呈现（设计稿手机分镜），避免与字段重复
const internalCardFields = [
  { label: '用户名', prop: 'username', num: true },
  { label: '角色', prop: 'role', slot: 'role' },
  { label: '最后登录', prop: 'last_login_at', slot: 'last_login_at' },
]

const internalFilterCount = computed(
  () => Object.values(internal.query).filter((value) => value !== '' && value !== null).length,
)

async function loadInternal() {
  internal.loading = true
  try {
    const params = { page: internal.page, page_size: internal.pageSize }
    if (internal.query.keyword.trim()) params.keyword = internal.query.keyword.trim()
    if (internal.query.role) params.role = internal.query.role
    if (internal.query.status !== '') params.status = Number(internal.query.status)
    const data = await api.listUsers(params)
    internal.rows = data?.items || []
    internal.total = Number(data?.meta?.total || 0)
  } catch {
    internal.rows = []
    internal.total = 0
  } finally {
    internal.loading = false
  }
}

function searchInternal() {
  internal.page = 1
  loadInternal()
}

function resetInternal() {
  internal.query.keyword = ''
  internal.query.role = ''
  internal.query.status = ''
  searchInternal()
}

function onInternalPage({ page, pageSize }) {
  internal.page = page
  if (pageSize) internal.pageSize = pageSize
  loadInternal()
}

// —— 新建 / 编辑我方账号 ——
const userDialog = reactive({ visible: false, mode: 'create', submitting: false })
const userFormRef = ref(null)
const userForm = reactive({
  id: null,
  username: '',
  real_name: '',
  role: 'buyer',
  initial_password: '',
  // 需求变更（2026-10）：是否要求首次登录修改密码，**默认关闭**
  must_change_password: false,
})

function isStrongPassword(value) {
  const text = String(value || '')
  return text.length >= 8 && text.length <= 20 && /[A-Za-z]/.test(text) && /\d/.test(text)
}

const userRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_]{4,20}$/, message: '用户名需为 4~20 位字母、数字或下划线', trigger: 'blur' },
  ],
  real_name: [{ max: 50, message: '姓名最长 50 个字符', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  initial_password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    {
      validator(_rule, value, callback) {
        if (isStrongPassword(value)) callback()
        else callback(new Error('初始密码需 8~20 位且至少包含字母与数字'))
      },
      trigger: 'blur',
    },
  ],
}

/** 建议密码：含大小写字母与数字（满足 FR-ACC-13 复杂度：8~20 位、字母+数字） */
function suggestPassword() {
  const letters = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz'
  const digits = '23456789'
  const pick = (pool) => pool[Math.floor(Math.random() * pool.length)]
  let body = ''
  for (let i = 0; i < 4; i += 1) body += pick(letters)
  for (let i = 0; i < 3; i += 1) body += pick(digits)
  return `Xj${pick(letters)}${body}`
}

function openCreateUser() {
  Object.assign(userForm, {
    id: null,
    username: '',
    real_name: '',
    role: 'buyer',
    initial_password: '',
    // 默认关闭：新建账号不强制首次登录改密（需求变更 2026-10）
    must_change_password: false,
  })
  userDialog.mode = 'create'
  userDialog.visible = true
  userFormRef.value?.clearValidate?.()
}

function openEditUser(row) {
  Object.assign(userForm, {
    id: row.id,
    username: row.username,
    real_name: row.real_name || '',
    role: row.role,
    initial_password: '',
  })
  userDialog.mode = 'edit'
  userDialog.visible = true
  userFormRef.value?.clearValidate?.()
}

async function submitUser() {
  const form = userFormRef.value
  if (!form) return
  try {
    await form.validate()
  } catch {
    return
  }

  userDialog.submitting = true
  try {
    if (userDialog.mode === 'create') {
      const requireChange = !!userForm.must_change_password
      await api.createUser({
        username: userForm.username.trim(),
        real_name: userForm.real_name.trim() || null,
        role: userForm.role,
        initial_password: userForm.initial_password,
        must_change_password: requireChange,
      })
      // 文案必须按开关区分，不能无条件提示需改密（需求变更 2026-10）
      ElMessage.success(
        requireChange ? '账号创建成功，该账号首次登录需修改密码' : '账号创建成功',
      )
    } else {
      await api.updateUser(userForm.id, {
        real_name: userForm.real_name.trim() || null,
        role: userForm.role,
      })
      ElMessage.success('账号信息已保存')
    }
    userDialog.visible = false
    await Promise.all([loadInternal(), loadCounts()])
  } catch (error) {
    // 降级最后一个管理员 → 409，原文展示（FR-ACC-06）
    if (error?.code === 40900 || error?.status === 409) {
      await showBackendReason('无法保存该账号', error, '操作被系统拒绝')
    }
  } finally {
    userDialog.submitting = false
  }
}

// —— 启用 / 停用 ——
async function toggleUser(row) {
  const turningOff = row.status === 1
  const name = row.real_name || row.username
  try {
    await ElMessageBox.confirm(
      turningOff
        ? `停用后「${name}」立即无法登录，已登录的会话同时失效；其历史单据与报价数据完整保留、报表仍可查询。`
        : `启用后「${name}」可重新登录。`,
      turningOff ? '确认停用该账号？' : '确认启用该账号？',
      {
        type: turningOff ? 'warning' : 'info',
        confirmButtonText: turningOff ? '确认停用' : '确认启用',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  try {
    // silent：错误由本页原样呈现，避免被通用 Toast 简化
    const updated = await api.toggleUserStatus(row.id, { silent: true })
    ElMessage.success(updated?.status === 1 ? '账号已启用' : '账号已停用')
    await Promise.all([loadInternal(), loadCounts()])
  } catch (error) {
    await showBackendReason(
      turningOff ? '无法停用该账号' : '无法启用该账号',
      error,
      '操作被系统拒绝，请稍后重试',
    )
  }
}

// ---------------------------------------------------------------------------
// B. 供货商账号
// ---------------------------------------------------------------------------
const supplier = reactive({
  loading: false,
  rows: [],
  page: 1,
  pageSize: 20,
  total: 0,
  // 设计稿把「状态」与「未首次登录」合成一个下拉：'1'/'0' 走 status，'never'/'logged' 走 login_state
  query: { keyword: '', state: '' },
})

const SUPPLIER_STATE_OPTIONS = [
  { value: '1', label: '启用' },
  { value: '0', label: '停用' },
  { value: 'never', label: '未首次登录' },
  { value: 'logged', label: '已登录过' },
]

const supplierColumns = [
  { prop: 'supplier_name', label: '供货商名称', width: 170 },
  { prop: 'username', label: '登录账号', width: 150, num: true },
  { prop: 'contact_name', label: '联系人', width: 110 },
  { prop: 'contact_phone', label: '联系电话', width: 140, num: true, hiddenOn: ['tablet'] },
  { prop: 'contact_email', label: '邮箱', width: 190, hiddenOn: ['tablet'] },
  { prop: 'status', label: '状态', width: 152 },
  { prop: 'last_login_at', label: '最后登录时间', width: 165, num: true, hiddenOn: ['tablet'] },
]

const supplierCardFields = [
  { label: '登录账号', prop: 'username', num: true },
  { label: '联系人', prop: 'contact_name' },
  { label: '电话', prop: 'contact_phone', num: true },
  { label: '邮箱', prop: 'contact_email' },
  { label: '最后登录', prop: 'last_login_at', slot: 'last_login_at' },
]

const supplierFilterCount = computed(
  () => Object.values(supplier.query).filter((value) => value !== '' && value !== null).length,
)

async function loadSupplier() {
  supplier.loading = true
  try {
    const params = { page: supplier.page, page_size: supplier.pageSize }
    if (supplier.query.keyword.trim()) params.keyword = supplier.query.keyword.trim()
    if (supplier.query.state === '1' || supplier.query.state === '0') {
      params.status = Number(supplier.query.state)
    } else if (supplier.query.state) {
      params.login_state = supplier.query.state
    }
    const data = await api.listSupplierAccounts(params)
    supplier.rows = data?.items || []
    supplier.total = Number(data?.meta?.total || 0)
  } catch {
    supplier.rows = []
    supplier.total = 0
  } finally {
    supplier.loading = false
  }
}

function searchSupplier() {
  supplier.page = 1
  loadSupplier()
}

function resetSupplier() {
  supplier.query.keyword = ''
  supplier.query.state = ''
  searchSupplier()
}

function onSupplierPage({ page, pageSize }) {
  supplier.page = page
  if (pageSize) supplier.pageSize = pageSize
  loadSupplier()
}

// —— 新建供货商账号（复用已有档案 / 新建档案）——
const supplierDialog = reactive({ visible: false, mode: 'existing', submitting: false })
const supplierFormRef = ref(null)
const supplierForm = reactive({
  supplier_id: null,
  supplier_name: '',
  credit_code: '',
  contact_name: '',
  contact_phone: '',
  contact_email: '',
  address: '',
  username: '',
  initial_password: '',
  // 需求变更（2026-10）：是否要求首次登录修改密码，**默认关闭**
  must_change_password: false,
})
const archiveOptions = ref([])

const supplierRules = {
  supplier_id: [
    {
      validator(_rule, value, callback) {
        if (supplierDialog.mode === 'existing' && !value) callback(new Error('请选择要绑定的供货商档案'))
        else callback()
      },
      trigger: 'change',
    },
  ],
  supplier_name: [
    {
      validator(_rule, value, callback) {
        if (supplierDialog.mode === 'new' && !String(value || '').trim()) {
          callback(new Error('请输入新的供货商名称'))
        } else callback()
      },
      trigger: 'blur',
    },
  ],
  username: [
    { required: true, message: '请输入登录账号', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_]{4,20}$/, message: '登录账号需为 4~20 位字母、数字或下划线', trigger: 'blur' },
  ],
  initial_password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    {
      validator(_rule, value, callback) {
        if (isStrongPassword(value)) callback()
        else callback(new Error('初始密码需 8~20 位且至少包含字母与数字'))
      },
      trigger: 'blur',
    },
  ],
  contact_phone: [
    {
      validator(_rule, value, callback) {
        const text = String(value || '').trim()
        if (!text || /^1\d{10}$/.test(text) || /^0\d{2,3}-?\d{7,8}$/.test(text)) callback()
        else callback(new Error('手机号 11 位，或座机如 010-88886666'))
      },
      trigger: 'blur',
    },
  ],
  contact_email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

/** 可选档案：只列未绑定账号的启用档案（一个档案只能绑定一个账号） */
async function loadArchiveOptions() {
  try {
    const data = await api.listSuppliers({ page: 1, page_size: 200, status: 1 })
    archiveOptions.value = (data?.items || []).filter((item) => !item.account_bound)
  } catch {
    archiveOptions.value = []
  }
}

async function openCreateSupplier(prefillSupplier = null) {
  Object.assign(supplierForm, {
    supplier_id: prefillSupplier?.id ?? null,
    supplier_name: '',
    credit_code: '',
    contact_name: prefillSupplier?.contact_name || '',
    contact_phone: prefillSupplier?.contact_phone || '',
    contact_email: prefillSupplier?.contact_email || '',
    address: prefillSupplier?.address || '',
    username: '',
    initial_password: suggestPassword(),
    // 默认关闭：新建账号不强制首次登录改密（需求变更 2026-10）
    must_change_password: false,
  })
  supplierDialog.mode = 'existing'
  supplierDialog.visible = true
  await loadArchiveOptions()
  supplierFormRef.value?.clearValidate?.()
}

async function submitSupplier() {
  const form = supplierFormRef.value
  if (!form) return
  try {
    await form.validate()
  } catch {
    return
  }

  supplierDialog.submitting = true
  try {
    const requireChange = !!supplierForm.must_change_password
    const payload = {
      username: supplierForm.username.trim(),
      initial_password: supplierForm.initial_password,
      must_change_password: requireChange,
    }
    if (supplierDialog.mode === 'existing') {
      payload.supplier_id = supplierForm.supplier_id
    } else {
      payload.supplier_name = supplierForm.supplier_name.trim()
      payload.credit_code = supplierForm.credit_code.trim() || null
      payload.contact_name = supplierForm.contact_name.trim() || null
      payload.contact_phone = supplierForm.contact_phone.trim() || null
      payload.contact_email = supplierForm.contact_email.trim() || null
      payload.address = supplierForm.address.trim() || null
    }
    await api.createSupplierAccount(payload)
    // 文案必须按开关区分，不能无条件提示需改密（需求变更 2026-10）
    ElMessage.success(
      requireChange ? '供货商账号创建成功，该账号首次登录需修改密码' : '供货商账号创建成功',
    )
    supplierDialog.visible = false
    await Promise.all([loadSupplier(), loadCounts()])
  } catch (error) {
    if (error?.code === 40900 || error?.status === 409) {
      await showBackendReason('无法创建供货商账号', error, '创建被系统拒绝')
    }
  } finally {
    supplierDialog.submitting = false
  }
}

// —— 编辑：账号本身不可改（后端无该接口），可编辑的是绑定档案的信息 ——
const archiveDialog = reactive({ visible: false, submitting: false })
const archiveFormRef = ref(null)
const archiveForm = reactive({
  id: null,
  username: '',
  name: '',
  credit_code: '',
  contact_name: '',
  contact_phone: '',
  contact_email: '',
  address: '',
  remark: '',
})

const archiveRules = {
  name: [{ required: true, message: '请输入供货商名称', trigger: 'blur' }],
  contact_phone: [
    {
      validator(_rule, value, callback) {
        const text = String(value || '').trim()
        if (!text || /^1\d{10}$/.test(text) || /^0\d{2,3}-?\d{7,8}$/.test(text)) callback()
        else callback(new Error('手机号 11 位，或座机如 010-88886666'))
      },
      trigger: 'blur',
    },
  ],
  contact_email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

async function openEditSupplierAccount(row) {
  if (!row.supplier_id) {
    ElMessage.warning('该账号未绑定供货商档案，无法编辑档案信息')
    return
  }
  archiveDialog.submitting = false
  Object.assign(archiveForm, {
    id: row.supplier_id,
    username: row.username,
    name: row.supplier_name || '',
    credit_code: '',
    contact_name: row.contact_name || '',
    contact_phone: row.contact_phone || '',
    contact_email: row.contact_email || '',
    address: '',
    remark: '',
  })
  archiveDialog.visible = true
  archiveFormRef.value?.clearValidate?.()
  try {
    // 列表只回传档案联系人快照，完整档案字段（信用代码/地址/备注）单独取一次
    const data = await api.listSuppliers({ page: 1, page_size: 200 })
    const full = (data?.items || []).find((item) => item.id === row.supplier_id)
    if (full) {
      Object.assign(archiveForm, {
        credit_code: full.credit_code || '',
        address: full.address || '',
        remark: full.remark || '',
        name: full.name || archiveForm.name,
        contact_name: full.contact_name || archiveForm.contact_name,
        contact_phone: full.contact_phone || archiveForm.contact_phone,
        contact_email: full.contact_email || archiveForm.contact_email,
      })
    }
  } catch {
    /* 取不到完整档案时至少可编辑联系人快照字段 */
  }
}

async function submitArchive() {
  const form = archiveFormRef.value
  if (!form) return
  try {
    await form.validate()
  } catch {
    return
  }
  archiveDialog.submitting = true
  try {
    await api.updateSupplier(archiveForm.id, {
      name: archiveForm.name.trim(),
      credit_code: archiveForm.credit_code.trim() || null,
      contact_name: archiveForm.contact_name.trim() || null,
      contact_phone: archiveForm.contact_phone.trim() || null,
      contact_email: archiveForm.contact_email.trim() || null,
      address: archiveForm.address.trim() || null,
      remark: archiveForm.remark.trim() || null,
    })
    ElMessage.success('供货商档案已保存')
    archiveDialog.visible = false
    await Promise.all([loadSupplier(), loadCounts()])
  } catch (error) {
    if (error?.code === 40900 || error?.status === 409) {
      await showBackendReason('无法保存供货商档案', error, '保存被系统拒绝')
    }
  } finally {
    archiveDialog.submitting = false
  }
}

async function toggleSupplierAccount(row) {
  const turningOff = row.status === 1
  const name = row.supplier_name || row.username
  try {
    await ElMessageBox.confirm(
      turningOff
        ? `停用后「${name}」的登录账号立即无法登录（含已登录会话失效），其历史询价单与报价数据完整保留、报表仍可查询。`
        : `启用后「${name}」的登录账号可重新登录。`,
      turningOff ? '确认停用该供货商账号？' : '确认启用该供货商账号？',
      {
        type: turningOff ? 'warning' : 'info',
        confirmButtonText: turningOff ? '确认停用' : '确认启用',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    await api.toggleSupplierAccountStatus(row.id, { silent: true })
    ElMessage.success(turningOff ? '供货商账号已停用' : '供货商账号已启用')
    await Promise.all([loadSupplier(), loadCounts()])
  } catch (error) {
    await showBackendReason(
      turningOff ? '无法停用该供货商账号' : '无法启用该供货商账号',
      error,
      '操作被系统拒绝，请稍后重试',
    )
  }
}

// —— 导出（FR-ACC-14 / FR-RWD-15：手机端导出照常可用，仅提示到电脑查看）——
async function exportSupplierList() {
  try {
    await api.exportSupplierAccounts({
      keyword: supplier.query.keyword.trim() || undefined,
      status:
        supplier.query.state === '1' || supplier.query.state === '0'
          ? Number(supplier.query.state)
          : undefined,
      login_state:
        supplier.query.state === 'never' || supplier.query.state === 'logged'
          ? supplier.query.state
          : undefined,
    })
    ElMessage.success(
      isMobile.value ? '文件已开始下载，建议在电脑上查看' : '供货商账号清单已导出（不含密码）',
    )
  } catch {
    /* request.js 已提示错误原因 */
  }
}

function exportInternalList() {
  // 后端未提供我方账号导出接口 → 前端 CSV 兜底（带 BOM，Excel 可直接打开）
  api.downloadCsv(
    `我方账号清单_${api.dateStamp()}.csv`,
    [
      { key: 'username', label: '用户名' },
      { key: 'real_name', label: '姓名' },
      { key: 'role_text', label: '角色' },
      { key: 'status_text', label: '状态' },
      { key: 'last_login_at', label: '最后登录时间' },
      { key: 'created_at', label: '创建时间' },
    ],
    internal.rows.map((row) => ({
      ...row,
      role_text: roleLabel(row.role),
      status_text: row.status === 1 ? '启用' : '已停用',
    })),
  )
  ElMessage.success(
    isMobile.value ? '文件已开始下载，建议在电脑上查看' : '已按当前查询条件导出本页账号（CSV）',
  )
}

async function exportImportTemplate() {
  try {
    await api.downloadImportTemplate()
    ElMessage.success(
      isMobile.value
        ? '模板已开始下载，建议在电脑上填写后导入'
        : '导入模板已下载，请按模板列填写后批量导入',
    )
  } catch {
    /* request.js 已提示错误原因 */
  }
}

// ---------------------------------------------------------------------------
// C. 重置密码（我方与供货商共用）
// ---------------------------------------------------------------------------
const resetDialog = reactive({
  visible: false,
  submitting: false,
  kind: 'user',
  id: null,
  name: '',
  role: '',
})
const resetFormRef = ref(null)
const resetForm = reactive({ new_password: '' })

const resetRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    {
      validator(_rule, value, callback) {
        if (isStrongPassword(value)) callback()
        else callback(new Error('新密码需 8~20 位且至少包含字母与数字'))
      },
      trigger: 'blur',
    },
  ],
}

function openResetPassword(row, kind) {
  Object.assign(resetDialog, {
    visible: true,
    submitting: false,
    kind,
    id: row.id,
    name: row.real_name || row.username,
    role: row.role,
  })
  resetForm.new_password = suggestPassword()
  resetFormRef.value?.clearValidate?.()
}

async function submitResetPassword() {
  const form = resetFormRef.value
  if (!form) return
  try {
    await form.validate()
  } catch {
    return
  }
  resetDialog.submitting = true
  try {
    const payload = { new_password: resetForm.new_password }
    const result =
      resetDialog.kind === 'supplier'
        ? await api.resetSupplierAccountPassword(resetDialog.id, payload)
        : await api.resetUserPassword(resetDialog.id, payload)
    // 后端 message 原文即"密码已重置，该账号下次登录需修改密码"
    ElMessage.success(result?.message || '密码已重置，该账号下次登录需修改密码')
    resetDialog.visible = false
    await Promise.all([loadInternal(), loadSupplier()])
  } catch {
    /* 错误提示由 request.js 统一给出（含 40001 字段校验原因） */
  } finally {
    resetDialog.submitting = false
  }
}

// ---------------------------------------------------------------------------
// D. 批量导入弹窗（手机端不提供入口，FR-RWD-14）
// ---------------------------------------------------------------------------
const importVisible = ref(false)

function openImport() {
  if (isMobile.value) {
    ElMessage.warning('批量导入请在电脑上操作')
    return
  }
  importVisible.value = true
}

async function onImported() {
  await Promise.all([loadSupplier(), loadArchiveOptions(), loadCounts()])
}

// ---------------------------------------------------------------------------
// 生命周期与页签切换
// ---------------------------------------------------------------------------
async function loadCurrentTab() {
  if (activeTab.value === 'internal') await loadInternal()
  else if (activeTab.value === 'supplier') await loadSupplier()
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  blockingNotice.value = ''
  syncTabToUrl(key)
  loadCurrentTab()
}

/** 浏览器前进/后退、直接改地址栏（?tab=...）时保持同步 */
watch(
  () => route.query.tab,
  (value) => {
    const next = normalizeTab(value)
    if (next === activeTab.value) return
    activeTab.value = next
    blockingNotice.value = ''
    loadCurrentTab()
  },
)

/** 从「字典维护 → 供货商档案」点「新建账号」跳转过来时，带档案预选开弹窗 */
async function handlePrefillFromQuery() {
  const prefillId = Number(route.query.new_account_for)
  if (!prefillId) return
  activeTab.value = 'supplier'
  syncTabToUrl('supplier')
  await loadSupplier()
  try {
    const data = await api.listSuppliers({ page: 1, page_size: 200 })
    const target = (data?.items || []).find((item) => item.id === prefillId)
    if (target) await openCreateSupplier(target)
  } catch {
    /* 忽略：用户仍可在列表里手动新建 */
  }
}

onMounted(async () => {
  // URL 里没有 tab 时补上当前页签，保证链接始终可分享/可刷新
  if (!route.query.tab) syncTabToUrl(activeTab.value)
  await Promise.all([loadCounts(), loadCurrentTab()])
  await handlePrefillFromQuery()
})

// ---------------------------------------------------------------------------
// 展示辅助
// ---------------------------------------------------------------------------
function roleLabel(role) {
  return role === 'admin' ? '管理员' : role === 'buyer' ? '采购员' : '供货商'
}

/** 状态徽标：停用 > 未首次登录 > 启用（一律带文字，颜色只作加速） */
function accountStatus(row) {
  if (row.status === 0) return { label: '已停用', tone: 'danger' }
  if (row.role === 'supplier' && !row.last_login_at) return { label: '未首次登录', tone: 'warn' }
  return { label: '启用', tone: 'ok' }
}

function loginText(row) {
  return formatDateTime(row.last_login_at)
}

function loginTextShort(row) {
  return row.last_login_at ? formatDateTimeShort(row.last_login_at) : '—'
}

function dateText(value) {
  return formatDateTime(value)
}

const userSummary = computed(() => {
  const enabled = internal.rows.filter((row) => row.status === 1).length
  const disabled = internal.rows.filter((row) => row.status === 0).length
  return `共 ${internal.total} 个账号 · 本页启用 ${enabled} · 停用 ${disabled}`
})

const supplierSummary = computed(() => {
  const never = supplier.rows.filter((row) => !row.last_login_at && row.status === 1).length
  return `共 ${supplier.total} 条 · 本页未首次登录 ${never}`
})
</script>

<template>
  <div class="sys-page account-page">
    <header class="sys-head">
      <div>
        <h3 class="sys-head__title">账号管理</h3>
        <p class="sys-head__desc">
          我方人员与供货商账号统一入口 · 账号只能停用不能删除（历史单据需保留创建人）
        </p>
      </div>

      <div class="sys-head__actions">
        <template v-if="activeTab === 'internal'">
          <el-button @click="exportInternalList">导出账号清单</el-button>
          <el-button v-if="!isMobile" type="primary" @click="openCreateUser">+ 新建我方账号</el-button>
        </template>

        <template v-else-if="activeTab === 'supplier'">
          <el-button @click="exportSupplierList">导出账号清单</el-button>
          <!-- 下载模板是文件下载（FR-RWD-15 允许手机端），批量导入重流程仅桌面端（FR-RWD-14） -->
          <el-button @click="exportImportTemplate">下载导入模板</el-button>
          <el-button v-if="!isMobile" @click="openImport">批量导入</el-button>
          <el-button v-if="!isMobile" type="primary" @click="openCreateSupplier()">
            + 新建供货商账号
          </el-button>
        </template>
      </div>
    </header>

    <!-- 手机端：批量导入引导到电脑（FR-RWD-14 / 设计稿 04-2 手机分镜）——
         只在「供货商账号」页签提示，字典页签不需要这句 -->
    <div v-if="isMobile && activeTab === 'supplier'" class="sys-alert sys-alert--info">
      <span class="sys-alert__icon">i</span>
      <div>
        <b>批量导入与新建账号请在电脑上操作。</b>
        手机端支持查看账号、启停用与重置密码。
      </div>
    </div>

    <!-- 后端拒绝原因原文常驻展示（如停用最后一个管理员 409） -->
    <div v-if="blockingNotice" class="sys-alert sys-alert--danger">
      <span class="sys-alert__icon">!</span>
      <div class="account-page__notice">
        <b>操作被系统拒绝：</b>{{ blockingNotice }}
        <button type="button" class="account-page__notice-close" @click="blockingNotice = ''">关闭</button>
      </div>
    </div>

    <nav class="sys-tabs" aria-label="账号管理页签">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        class="sys-tab"
        :class="{ 'is-on': activeTab === tab.key }"
        :aria-current="activeTab === tab.key ? 'page' : undefined"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
        <span class="sys-tab__count">{{
          tab.key === 'internal' ? internalTotal : supplierTotal
        }}</span>
      </button>
    </nav>

    <!-- ==================== 我方人员 ==================== -->
    <template v-if="activeTab === 'internal'">
      <FilterDrawer
        :active-count="internalFilterCount"
        :loading="internal.loading"
        @search="searchInternal"
        @reset="resetInternal"
      >
        <el-form-item label="用户名 / 姓名">
          <el-input
            v-model="internal.query.keyword"
            class="f-field"
            placeholder="用户名或姓名"
            clearable
            @keyup.enter="searchInternal"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="internal.query.role" class="f-field" placeholder="全部角色" clearable>
            <el-option
              v-for="item in ROLE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="internal.query.status" class="f-field" placeholder="全部状态" clearable>
            <el-option label="启用" value="1" />
            <el-option label="停用" value="0" />
          </el-select>
        </el-form-item>
      </FilterDrawer>

      <DataTable
        :data="internal.rows"
        :columns="internalColumns"
        :card-fields="internalCardFields"
        card-title="real_name"
        :loading="internal.loading"
        :pagination="{ page: internal.page, pageSize: internal.pageSize, total: internal.total }"
        empty-text="暂无我方账号"
        @page-change="onInternalPage"
      >
        <template #username="{ row }"><span class="sys-num">{{ row.username }}</span></template>

        <template #real_name="{ row }">
          <span class="sys-strong">{{ row.real_name || '—' }}</span>
        </template>

        <template #role="{ row }">
          <StatusBadge :status="row.role" />
        </template>

        <template #status="{ row }">
          <span class="account-page__status">
            <StatusBadge :label="accountStatus(row).label" :tone="accountStatus(row).tone" />
            <span v-if="row.must_change_password" class="sys-sub">需改密</span>
          </span>
        </template>

        <template #last_login_at="{ row }">
          <span class="sys-num">{{ loginText(row) }}</span>
        </template>

        <template #created_at="{ row }">
          <span class="sys-num sys-sub">{{ dateText(row.created_at) }}</span>
        </template>

        <template #card-last_login_at="{ row }">
          <span class="sys-num">{{ loginTextShort(row) }}</span>
        </template>

        <!-- DataTable 手机卡片按 `card-<slot||prop>` 取名，桌面插槽不会自动复用 -->
        <template #card-role="{ row }">
          <StatusBadge :status="row.role" />
        </template>

        <template #card-extra="{ row }">
          <span class="account-page__status">
            <StatusBadge :label="accountStatus(row).label" :tone="accountStatus(row).tone" />
            <span v-if="row.must_change_password" class="sys-sub">需改密</span>
          </span>
        </template>

        <template #actions="{ row }">
          <div class="sys-ops">
            <el-button link type="primary" @click="openEditUser(row)">编辑</el-button>
            <el-button link type="primary" @click="openResetPassword(row, 'user')">重置密码</el-button>
            <el-button link :type="row.status === 1 ? 'danger' : 'primary'" @click="toggleUser(row)">
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
          </div>
        </template>
      </DataTable>

      <div class="sys-card__foot account-page__foot">
        <span>{{ userSummary }}</span>
        <span class="sys-sub">账号不可删除，仅可停用（历史单据与操作日志需保留创建人）</span>
      </div>
    </template>

    <!-- ==================== 供货商账号 ==================== -->
    <template v-else-if="activeTab === 'supplier'">
      <FilterDrawer
        :active-count="supplierFilterCount"
        :loading="supplier.loading"
        @search="searchSupplier"
        @reset="resetSupplier"
      >
        <el-form-item label="供货商名称 / 登录账号">
          <el-input
            v-model="supplier.query.keyword"
            class="f-field"
            placeholder="供货商名称 / 登录账号 / 联系人"
            clearable
            @keyup.enter="searchSupplier"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="supplier.query.state" class="f-field" placeholder="全部状态" clearable>
            <el-option
              v-for="item in SUPPLIER_STATE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </FilterDrawer>

      <DataTable
        :data="supplier.rows"
        :columns="supplierColumns"
        :card-fields="supplierCardFields"
        card-title="supplier_name"
        :loading="supplier.loading"
        :pagination="{ page: supplier.page, pageSize: supplier.pageSize, total: supplier.total }"
        empty-text="暂无供货商账号"
        :actions-width="190"
        @page-change="onSupplierPage"
      >
        <template #supplier_name="{ row }">
          <span class="sys-strong">{{ row.supplier_name || '—' }}</span>
          <div v-if="row.status === 0" class="sys-sub">已停止合作</div>
        </template>

        <template #username="{ row }"><span class="sys-num">{{ row.username }}</span></template>
        <template #contact_phone="{ row }">
          <span class="sys-num">{{ row.contact_phone || '—' }}</span>
        </template>
        <template #contact_email="{ row }">
          <span class="sys-sub">{{ row.contact_email || '—' }}</span>
        </template>

        <template #status="{ row }">
          <span class="account-page__status">
            <StatusBadge :label="accountStatus(row).label" :tone="accountStatus(row).tone" />
            <span v-if="row.must_change_password && row.status === 1" class="sys-sub">需改密</span>
          </span>
        </template>

        <template #last_login_at="{ row }">
          <span v-if="row.last_login_at" class="sys-num">{{ loginText(row) }}</span>
          <span v-else class="sys-sub">—</span>
        </template>

        <template #card-last_login_at="{ row }">
          <span class="sys-num">{{ loginTextShort(row) }}</span>
        </template>

        <template #card-extra="{ row }">
          <StatusBadge :label="accountStatus(row).label" :tone="accountStatus(row).tone" />
        </template>

        <template #actions="{ row }">
          <div class="sys-ops">
            <el-button link type="primary" @click="openResetPassword(row, 'supplier')">重置密码</el-button>
            <el-button link type="primary" @click="openEditSupplierAccount(row)">编辑</el-button>
            <el-button
              link
              :type="row.status === 1 ? 'danger' : 'primary'"
              @click="toggleSupplierAccount(row)"
            >
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
          </div>
        </template>
      </DataTable>

      <div class="sys-card__foot account-page__foot">
        <span>{{ supplierSummary }}</span>
        <span class="sys-sub">供货商账号与档案一对一绑定 · 账号不可删除，仅可停用</span>
      </div>

      <div class="sys-alert sys-alert--warn account-page__hint">
        <span class="sys-alert__icon">!</span>
        <div>
          <b>停用效果：</b>该供货商账号立即无法登录（含已登录会话失效），其历史询价单与报价数据完整保留、报表仍可查询。
        </div>
      </div>
    </template>
  </div>

  <!-- ==================== 新建 / 编辑我方账号 ==================== -->
  <el-dialog
    v-model="userDialog.visible"
    :title="userDialog.mode === 'create' ? '新建我方账号' : '编辑我方账号'"
    :width="isMobile ? '94%' : '520px'"
    :close-on-click-modal="false"
  >
    <el-form
      ref="userFormRef"
      class="sys-form"
      :model="userForm"
      :rules="userRules"
      label-position="top"
      @submit.prevent
    >
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="userForm.username"
          :disabled="userDialog.mode === 'edit'"
          placeholder="4~20 位字母、数字或下划线"
          maxlength="20"
        />
        <div v-if="userDialog.mode === 'edit'" class="sys-field-hint">用户名创建后不可修改</div>
      </el-form-item>

      <el-form-item label="姓名" prop="real_name">
        <el-input v-model="userForm.real_name" placeholder="真实姓名，用于日志与单据署名" maxlength="50" />
      </el-form-item>

      <el-form-item label="角色" prop="role">
        <el-radio-group v-model="userForm.role">
          <el-radio value="buyer">采购员</el-radio>
          <el-radio value="admin">管理员</el-radio>
        </el-radio-group>
        <div class="sys-field-hint">
          系统至少需保留一个启用的管理员账号；把最后一个管理员降级会被后端拒绝并给出原因。
        </div>
      </el-form-item>

      <el-form-item v-if="userDialog.mode === 'create'" label="初始密码" prop="initial_password">
        <el-input
          v-model="userForm.initial_password"
          placeholder="8~20 位，至少含字母与数字"
          show-password
        />
        <div class="sys-field-hint">
          规则：8~20 位且至少包含字母与数字
          <el-button link type="primary" @click="userForm.initial_password = suggestPassword()">
            生成建议密码
          </el-button>
        </div>
      </el-form-item>

      <!-- 需求变更（2026-10）：默认关闭；开启后该账号首次登录会被强制改密（40101） -->
      <el-form-item v-if="userDialog.mode === 'create'" label="要求首次登录修改密码">
        <div class="account-page__switch">
          <el-switch
            v-model="userForm.must_change_password"
            active-text="开启"
            inactive-text="关闭（默认）"
          />
        </div>
        <div class="sys-field-hint">
          关闭（默认）：该账号可直接用初始密码登录并使用业务功能；
          开启：首次登录会被强制跳转到修改密码页，改密后旧会话立即失效。
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button class="dlg-btn" @click="userDialog.visible = false">取消</el-button>
      <el-button class="dlg-btn" type="primary" :loading="userDialog.submitting" @click="submitUser">
        {{ userDialog.mode === 'create' ? '创建账号' : '保存' }}
      </el-button>
    </template>
  </el-dialog>

  <!-- ==================== 新建供货商账号 ==================== -->
  <el-dialog
    v-model="supplierDialog.visible"
    title="新建供货商账号"
    :width="isMobile ? '94%' : '640px'"
    :close-on-click-modal="false"
  >
    <el-form
      ref="supplierFormRef"
      class="sys-form"
      :model="supplierForm"
      :rules="supplierRules"
      label-position="top"
      @submit.prevent
    >
      <el-form-item label="供货商档案">
        <el-radio-group v-model="supplierDialog.mode">
          <el-radio value="existing">选择已有档案</el-radio>
          <el-radio value="new">新建档案并绑定</el-radio>
        </el-radio-group>
        <div class="sys-field-hint">一个档案只能绑定一个账号（一对一）。</div>
      </el-form-item>

      <el-form-item v-if="supplierDialog.mode === 'existing'" label="选择档案" prop="supplier_id">
        <el-select
          v-model="supplierForm.supplier_id"
          filterable
          clearable
          placeholder="仅列出未绑定账号的档案"
          style="width: 100%"
        >
          <el-option v-for="item in archiveOptions" :key="item.id" :label="item.name" :value="item.id">
            <span>{{ item.name }}</span>
            <span class="sys-sub"> · {{ item.contact_name || '无联系人' }} {{ item.contact_phone || '' }}</span>
          </el-option>
        </el-select>
        <div v-if="!archiveOptions.length" class="sys-field-hint">
          没有未绑定的档案，可切换到「新建档案并绑定」。
        </div>
      </el-form-item>

      <template v-else>
        <el-form-item label="供货商名称" prop="supplier_name">
          <el-input v-model="supplierForm.supplier_name" placeholder="营业执照名称，唯一" maxlength="100" />
        </el-form-item>
        <div class="grid2">
          <el-form-item label="统一社会信用代码">
            <el-input v-model="supplierForm.credit_code" placeholder="可空" maxlength="30" />
          </el-form-item>
          <el-form-item label="联系人">
            <el-input v-model="supplierForm.contact_name" placeholder="可空" maxlength="50" />
          </el-form-item>
          <el-form-item label="联系电话" prop="contact_phone">
            <el-input v-model="supplierForm.contact_phone" placeholder="手机号或座机" maxlength="30" />
          </el-form-item>
          <el-form-item label="邮箱" prop="contact_email">
            <el-input v-model="supplierForm.contact_email" placeholder="可空" maxlength="100" />
          </el-form-item>
        </div>
        <el-form-item label="地址">
          <el-input v-model="supplierForm.address" placeholder="可空" maxlength="200" />
        </el-form-item>
      </template>

      <el-form-item label="登录账号" prop="username">
        <el-input v-model="supplierForm.username" placeholder="4~20 位字母、数字或下划线" maxlength="20" />
      </el-form-item>

      <el-form-item label="初始密码" prop="initial_password">
        <el-input
          v-model="supplierForm.initial_password"
          placeholder="8~20 位，至少含字母与数字"
          show-password
        />
        <div class="sys-field-hint">
          规则：8~20 位且至少包含字母与数字
          <el-button link type="primary" @click="supplierForm.initial_password = suggestPassword()">
            生成建议密码
          </el-button>
        </div>
      </el-form-item>

      <!-- 需求变更（2026-10）：默认关闭；开启后该账号首次登录会被强制改密（40101） -->
      <el-form-item label="要求首次登录修改密码">
        <div class="account-page__switch">
          <el-switch
            v-model="supplierForm.must_change_password"
            active-text="开启"
            inactive-text="关闭（默认）"
          />
        </div>
        <div class="sys-field-hint">
          关闭（默认）：供货商可直接用初始密码登录并报价；
          开启：首次登录会被强制跳转到修改密码页。
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button class="dlg-btn" @click="supplierDialog.visible = false">取消</el-button>
      <el-button
        class="dlg-btn"
        type="primary"
        :loading="supplierDialog.submitting"
        @click="submitSupplier"
      >
        创建账号
      </el-button>
    </template>
  </el-dialog>

  <!-- ==================== 编辑绑定档案（供货商账号无独立编辑接口） ==================== -->
  <el-dialog
    v-model="archiveDialog.visible"
    title="编辑供货商档案"
    :width="isMobile ? '94%' : '640px'"
    :close-on-click-modal="false"
  >
    <el-form
      ref="archiveFormRef"
      class="sys-form"
      :model="archiveForm"
      :rules="archiveRules"
      label-position="top"
      @submit.prevent
    >
      <div class="sys-alert sys-alert--info">
        <span class="sys-alert__icon">i</span>
        <div>
          登录账号 <span class="sys-num">{{ archiveForm.username }}</span>
          创建后不可修改；此处修改其绑定的供货商档案信息，档案被停用时该账号会同步停用。
        </div>
      </div>

      <el-form-item label="供货商名称" prop="name">
        <el-input v-model="archiveForm.name" maxlength="100" />
      </el-form-item>
      <div class="grid2">
        <el-form-item label="统一社会信用代码">
          <el-input v-model="archiveForm.credit_code" maxlength="30" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="archiveForm.contact_name" maxlength="50" />
        </el-form-item>
        <el-form-item label="联系电话" prop="contact_phone">
          <el-input v-model="archiveForm.contact_phone" maxlength="30" />
        </el-form-item>
        <el-form-item label="邮箱" prop="contact_email">
          <el-input v-model="archiveForm.contact_email" maxlength="100" />
        </el-form-item>
      </div>
      <el-form-item label="地址">
        <el-input v-model="archiveForm.address" maxlength="200" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="archiveForm.remark" type="textarea" :rows="2" maxlength="500" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button class="dlg-btn" @click="archiveDialog.visible = false">取消</el-button>
      <el-button class="dlg-btn" type="primary" :loading="archiveDialog.submitting" @click="submitArchive">
        保存
      </el-button>
    </template>
  </el-dialog>

  <!-- ==================== 重置密码 ==================== -->
  <el-dialog
    v-model="resetDialog.visible"
    title="重置密码"
    :width="isMobile ? '94%' : '480px'"
    :close-on-click-modal="false"
  >
    <el-form
      ref="resetFormRef"
      class="sys-form"
      :model="resetForm"
      :rules="resetRules"
      label-position="top"
      @submit.prevent
    >
      <div class="sys-alert sys-alert--warn">
        <span class="sys-alert__icon">!</span>
        <div>
          正在为「<b>{{ resetDialog.name }}</b>」（{{ roleLabel(resetDialog.role) }}）重置密码。
          重置后<b>该账号下次登录需修改密码</b>，其已登录会话立即失效。
        </div>
      </div>

      <el-form-item label="新密码" prop="new_password">
        <el-input v-model="resetForm.new_password" show-password placeholder="8~20 位，至少含字母与数字" />
        <div class="sys-field-hint">
          规则：8~20 位且至少包含字母与数字
          <el-button link type="primary" @click="resetForm.new_password = suggestPassword()">
            生成建议密码
          </el-button>
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button class="dlg-btn" @click="resetDialog.visible = false">取消</el-button>
      <el-button class="dlg-btn" type="primary" :loading="resetDialog.submitting" @click="submitResetPassword">
        确认重置
      </el-button>
    </template>
  </el-dialog>

  <!-- ==================== 批量导入（仅桌面端入口） ==================== -->
  <SupplierImport v-model="importVisible" @imported="onImported" />
</template>

<style scoped lang="scss">
@use './system-shared';
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.f-field {
  width: 100%;
}

@include bp.tablet-up {
  .f-field {
    width: 220px;
  }
}

.account-page__status {
  display: inline-flex;
  align-items: center;
  gap: v.$sp-1;
  flex-wrap: wrap;
}

.account-page__switch {
  display: flex;
  align-items: center;
  min-height: v.$touch-target;
}

.account-page__notice {
  position: relative;
  padding-right: 46px;
}

.account-page__notice-close {
  position: absolute;
  top: -2px;
  right: 0;
  padding: 2px 6px;
  font-size: v.$fs-xs;
  color: inherit;
  background: transparent;
  border: 1px solid currentColor;
  border-radius: v.$r-sm;
  cursor: pointer;
  opacity: 0.75;

  &:hover {
    opacity: 1;
  }
}

.account-page__foot {
  margin-top: v.$sp-3;
  justify-content: space-between;
}

.account-page__hint {
  margin-top: v.$sp-3;
}

.grid2 {
  display: grid;
  gap: 0 v.$sp-3;

  @include bp.tablet-up {
    grid-template-columns: 1fr 1fr;
  }
}

// 弹窗底部按钮：手机端热区 ≥44px（FR-RWD-06）
.dlg-btn {
  @include bp.mobile {
    min-height: v.$touch-target;
    margin-left: v.$sp-2;
  }
}
</style>
