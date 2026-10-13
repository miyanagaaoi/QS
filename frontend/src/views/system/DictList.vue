<script setup>
/**
 * DictList — 系统管理 · 字典维护（独立页面，三个页签）
 * （PRD 5.4.3 / FR-MST-01~04，设计稿 04-3）
 * ---------------------------------------------------------------------------
 * 需求方最终结构（2026-10 更正）：「字典维护」恢复为独立菜单/独立页面，
 * 页面内三个页签：① 计量单位 ② 税率 ③ 供货商档案；UI 风格与「账号管理」页一致。
 *   - 页签状态走 URL query（?tab=unit|tax|supplier），刷新/分享链接可定位
 *   - 供货商档案只在**这里**维护（账号管理页不再引用 SupplierArchivePanel）
 *
 * 三条硬约束：
 *  1. 被单据引用的计量单位**不可删除，只能停用**（后端也没有删除接口），
 *     列表用 referenced_count 在名称下方标注"已被 N 张单据引用，不可删除，仅可停用"；
 *  2. 税率字典的**默认项全站唯一**：设置新默认时后端会自动清除旧的默认项；
 *  3. 供货商档案与账号一对一绑定，未绑定账号的档案给出「新建账号」入口
 *     （跳「账号管理 → 供货商账号」页签并预选该档案）。
 *
 * 接口：GET/POST/PUT /admin/units、/admin/taxes、/admin/suppliers（全部实测通过）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useBreakpoint } from '@/composables/useBreakpoint'

import * as api from './adminApi'
import SupplierArchivePanel from './SupplierArchivePanel.vue'

defineOptions({ name: 'SystemDictList' })

const { isMobile } = useBreakpoint()
const route = useRoute()
const router = useRouter()

const archiveRef = ref(null)

// ---------------------------------------------------------------------------
// 页签：① 计量单位 ② 税率 ③ 供货商档案（与账号管理页同一套 .sys-tabs 样式）
// ---------------------------------------------------------------------------
const TABS = [
  { key: 'unit', label: '计量单位' },
  { key: 'tax', label: '税率' },
  { key: 'supplier', label: '供货商档案' },
]
const TAB_KEYS = TABS.map((tab) => tab.key)

function normalizeTab(value) {
  const key = String(value || '')
  return TAB_KEYS.includes(key) ? key : 'unit'
}

const activeTab = ref(normalizeTab(route.query.tab))

/** 页签写回 URL（replace：刷新/分享可用，不污染浏览器历史） */
function syncTabToUrl(key) {
  const query = { ...route.query, tab: key }
  router.replace({ path: '/system/dict', query }).catch(() => {})
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  syncTabToUrl(key)
}

/** 支持前进/后退、直接改地址栏（?tab=...） */
watch(
  () => route.query.tab,
  (value) => {
    const next = normalizeTab(value)
    if (next !== activeTab.value) activeTab.value = next
  },
)

// ---------------------------------------------------------------------------
// 计量单位
// ---------------------------------------------------------------------------
const units = reactive({ loading: false, rows: [] })

const unitColumns = [
  // 宽度 250：保证「已被 N 张单据引用，不可删除，仅可停用」在桌面端一行显示（不折行）
  { prop: 'name', label: '单位名称', width: 250 },
  { prop: 'sort', label: '排序', width: 90, align: 'center', num: true },
  { prop: 'status', label: '状态', width: 100 },
]

const unitCardFields = [
  { label: '排序', prop: 'sort', num: true },
  { label: '状态', prop: 'status', slot: 'status' },
  { label: '引用情况', prop: 'referenced_count', slot: 'referenced_count' },
]

async function loadUnits() {
  units.loading = true
  try {
    const data = await api.listUnits()
    units.rows = Array.isArray(data) ? data : data?.items || []
  } catch {
    units.rows = []
  } finally {
    units.loading = false
  }
}

const unitDialog = reactive({ visible: false, mode: 'create', submitting: false })
const unitFormRef = ref(null)
const unitForm = reactive({ id: null, name: '', sort: 0 })

const unitRules = {
  name: [
    { required: true, message: '请输入单位名称', trigger: 'blur' },
    { max: 20, message: '单位名称最长 20 个字符', trigger: 'blur' },
  ],
}

function openUnitCreate() {
  const nextSort = units.rows.reduce((max, row) => Math.max(max, Number(row.sort) || 0), 0) + 1
  Object.assign(unitForm, { id: null, name: '', sort: nextSort })
  unitDialog.mode = 'create'
  unitDialog.visible = true
  unitFormRef.value?.clearValidate?.()
}

function openUnitEdit(row) {
  Object.assign(unitForm, { id: row.id, name: row.name, sort: Number(row.sort) || 0 })
  unitDialog.mode = 'edit'
  unitDialog.visible = true
  unitFormRef.value?.clearValidate?.()
}

async function submitUnit() {
  const instance = unitFormRef.value
  if (!instance) return
  try {
    await instance.validate()
  } catch {
    return
  }
  unitDialog.submitting = true
  try {
    if (unitDialog.mode === 'create') {
      await api.createUnit({ name: unitForm.name.trim(), sort: Number(unitForm.sort) || 0 })
      ElMessage.success('计量单位已新增')
    } else {
      await api.updateUnit(unitForm.id, {
        name: unitForm.name.trim(),
        sort: Number(unitForm.sort) || 0,
      })
      ElMessage.success('计量单位已保存')
    }
    unitDialog.visible = false
    await loadUnits()
  } catch (error) {
    if (error?.code === 40900 || error?.status === 409) {
      ElMessageBox.alert(String(error.message || '保存被系统拒绝'), '无法保存计量单位', {
        type: 'error',
        confirmButtonText: '我知道了',
      }).catch(() => {})
    }
  } finally {
    unitDialog.submitting = false
  }
}

async function toggleUnit(row) {
  const turningOff = row.status === 1
  const refText = row.referenced_count
    ? `该单位已被 ${row.referenced_count} 张单据引用，不可删除，停用后历史单据仍可正常查看。`
    : '该单位未被任何单据引用。'
  try {
    await ElMessageBox.confirm(
      turningOff
        ? `${refText}停用后新建询价单时不再出现在单位下拉中。`
        : '启用后新建询价单时可重新选择该单位。',
      turningOff ? '确认停用该计量单位？' : '确认启用该计量单位？',
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
    await api.updateUnit(row.id, { status: turningOff ? 0 : 1 })
    ElMessage.success(turningOff ? '计量单位已停用' : '计量单位已启用')
    await loadUnits()
  } catch (error) {
    ElMessageBox.alert(String(error?.message || '操作被系统拒绝'), '无法变更计量单位状态', {
      type: 'error',
      confirmButtonText: '我知道了',
    }).catch(() => {})
  }
}

// ---------------------------------------------------------------------------
// 税率
// ---------------------------------------------------------------------------
const taxes = reactive({ loading: false, rows: [] })

const taxColumns = [
  { prop: 'label', label: '显示名', width: 130 },
  { prop: 'rate', label: '税率值', width: 110, num: true },
  { prop: 'is_default', label: '默认', width: 100 },
  { prop: 'status', label: '状态', width: 100 },
]

// 手机卡片：默认项以标题右侧徽标呈现，避免与字段重复
const taxCardFields = [
  { label: '税率值', prop: 'rate', num: true },
  { label: '状态', prop: 'status', slot: 'status' },
]

async function loadTaxes() {
  taxes.loading = true
  try {
    const data = await api.listTaxes()
    taxes.rows = Array.isArray(data) ? data : data?.items || []
  } catch {
    taxes.rows = []
  } finally {
    taxes.loading = false
  }
}

const taxDialog = reactive({ visible: false, mode: 'create', submitting: false })
const taxFormRef = ref(null)
const taxForm = reactive({ id: null, percent: 13, label: '13%', is_default: false, sort: 0 })

const taxRules = {
  percent: [
    { required: true, message: '请输入税率百分比', trigger: 'blur' },
    {
      validator(_rule, value, callback) {
        const num = Number(value)
        if (!Number.isFinite(num) || num < 0 || num > 100) {
          callback(new Error('税率需为 0~100 之间的百分比'))
        } else callback()
      },
      trigger: 'blur',
    },
  ],
  label: [
    { required: true, message: '请输入显示名（如 13%）', trigger: 'blur' },
    { max: 20, message: '显示名最长 20 个字符', trigger: 'blur' },
  ],
}

/** '0.1300' → 13（编辑时回填百分比输入框） */
function rateToPercent(rate) {
  const num = Number(rate)
  return Number.isFinite(num) ? Math.round(num * 10000) / 100 : 0
}

/** 百分比 → 后端要求的 0~1 小数字符串（直接给字符串，避免 JS 浮点误差） */
function percentToRate(percent) {
  const num = Number(percent)
  return (num / 100).toFixed(4)
}

function openTaxCreate() {
  const nextSort = taxes.rows.reduce((max, row) => Math.max(max, Number(row.sort) || 0), 0) + 1
  Object.assign(taxForm, { id: null, percent: 13, label: '13%', is_default: false, sort: nextSort })
  taxDialog.mode = 'create'
  taxDialog.visible = true
  taxFormRef.value?.clearValidate?.()
}

function openTaxEdit(row) {
  Object.assign(taxForm, {
    id: row.id,
    percent: rateToPercent(row.rate),
    label: row.label,
    is_default: !!row.is_default,
    sort: Number(row.sort) || 0,
  })
  taxDialog.mode = 'edit'
  taxDialog.visible = true
  taxFormRef.value?.clearValidate?.()
}

function syncTaxLabel() {
  taxForm.label = `${Number(taxForm.percent) || 0}%`
}

async function submitTax() {
  const instance = taxFormRef.value
  if (!instance) return
  try {
    await instance.validate()
  } catch {
    return
  }
  taxDialog.submitting = true
  const payload = {
    rate: percentToRate(taxForm.percent),
    label: taxForm.label.trim(),
    is_default: !!taxForm.is_default,
    sort: Number(taxForm.sort) || 0,
  }
  try {
    if (taxDialog.mode === 'create') {
      await api.createTax(payload)
      ElMessage.success(payload.is_default ? '税率已新增并设为默认（原默认项已自动取消）' : '税率已新增')
    } else {
      await api.updateTax(taxForm.id, payload)
      ElMessage.success(payload.is_default ? '税率已保存并设为默认（原默认项已自动取消）' : '税率已保存')
    }
    taxDialog.visible = false
    await loadTaxes()
  } catch (error) {
    if (error?.code === 40900 || error?.status === 409) {
      ElMessageBox.alert(String(error.message || '保存被系统拒绝'), '无法保存税率', {
        type: 'error',
        confirmButtonText: '我知道了',
      }).catch(() => {})
    }
  } finally {
    taxDialog.submitting = false
  }
}

async function toggleTax(row) {
  const turningOff = row.status === 1
  if (turningOff && row.is_default) {
    ElMessage.warning('默认税率不能停用，请先把其他税率设为默认')
    return
  }
  try {
    await ElMessageBox.confirm(
      turningOff
        ? '停用后供货商报价时不再能选择该税率，已提交的报价不受影响。'
        : '启用后供货商报价时可重新选择该税率。',
      turningOff ? '确认停用该税率？' : '确认启用该税率？',
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
    await api.updateTax(row.id, { status: turningOff ? 0 : 1 })
    ElMessage.success(turningOff ? '税率已停用' : '税率已启用')
    await loadTaxes()
  } catch (error) {
    ElMessageBox.alert(String(error?.message || '操作被系统拒绝'), '无法变更税率状态', {
      type: 'error',
      confirmButtonText: '我知道了',
    }).catch(() => {})
  }
}

// ---------------------------------------------------------------------------
// 页头统计 / 档案联动
// ---------------------------------------------------------------------------
const enabledUnits = computed(() => units.rows.filter((row) => row.status === 1).length)
const enabledTaxes = computed(() => taxes.rows.filter((row) => row.status === 1).length)

/** 未绑定账号的档案 → 跳到账号管理的供货商账号页签并预选该档案 */
function onCreateAccountForArchive(row) {
  router.push({
    path: '/system/account',
    query: { tab: 'supplier', new_account_for: String(row.id) },
  })
}

onMounted(() => {
  // URL 里没有 tab 时补上，保证链接可分享
  if (!route.query.tab) syncTabToUrl(activeTab.value)
  // 三个页签的数据都很轻（单位/税率各 1 个请求），一次拉齐便于页签即时切换
  Promise.all([loadUnits(), loadTaxes()])
})
</script>

<template>
  <div class="sys-page dict-page">
    <header class="sys-head">
      <div>
        <h3 class="sys-head__title">字典维护</h3>
        <p class="sys-head__desc">
          计量单位 <b class="sys-num">{{ units.rows.length }}</b> 项 ·
          税率 <b class="sys-num">{{ taxes.rows.length }}</b> 项 ·
          供货商档案与账号一对一绑定 · 字典项被单据引用后不可删除，仅可停用
        </p>
      </div>
    </header>

    <nav class="sys-tabs" aria-label="字典维护页签">
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
        <span v-if="tab.key === 'unit'" class="sys-tab__count">{{ units.rows.length }}</span>
        <span v-else-if="tab.key === 'tax'" class="sys-tab__count">{{ taxes.rows.length }}</span>
      </button>
    </nav>

    <!-- ==================== ① 计量单位 ==================== -->
    <section v-if="activeTab === 'unit'" class="sys-card">
      <div class="sys-card__head">
      <b class="sys-card__title">计量单位</b>
      <span class="sys-card__sub">启用 {{ enabledUnits }} / {{ units.rows.length }}</span>
      <div class="sys-card__right">
        <el-button size="small" @click="openUnitCreate">+ 新增</el-button>
      </div>
      </div>

      <DataTable
      :data="units.rows"
        :columns="unitColumns"
        :card-fields="unitCardFields"
        card-title="name"
        :loading="units.loading"
        empty-text="暂无计量单位"
        :actions-width="150"
      >
        <template #name="{ row }">
          <span class="sys-strong">{{ row.name }}</span>
          <div v-if="row.referenced_count" class="sys-sub dict-page__ref">
            已被 {{ row.referenced_count }} 张单据引用，不可删除，仅可停用
          </div>
        </template>

        <template #referenced_count="{ row }">
          <span v-if="row.referenced_count">被 {{ row.referenced_count }} 张单据引用</span>
          <span v-else class="sys-sub">未被引用</span>
        </template>

        <template #sort="{ row }"><span class="sys-num">{{ row.sort }}</span></template>

        <template #status="{ row }">
          <StatusBadge
            :label="row.status === 1 ? '启用' : '已停用'"
            :tone="row.status === 1 ? 'ok' : 'muted'"
          />
        </template>

        <!-- DataTable 手机卡片按 `card-<slot||prop>` 取名，桌面插槽不会自动复用 -->
        <template #card-status="{ row }">
          <StatusBadge
            :label="row.status === 1 ? '启用' : '已停用'"
            :tone="row.status === 1 ? 'ok' : 'muted'"
          />
        </template>

        <template #card-referenced_count="{ row }">
          <span v-if="row.referenced_count">被 {{ row.referenced_count }} 张单据引用，不可删除</span>
          <span v-else class="sys-sub">未被引用</span>
        </template>

        <template #actions="{ row }">
          <div class="sys-ops">
            <el-button link type="primary" @click="openUnitEdit(row)">编辑</el-button>
            <el-button link :type="row.status === 1 ? 'danger' : 'primary'" @click="toggleUnit(row)">
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
          </div>
        </template>
      </DataTable>

      <div class="sys-card__foot">
        <span class="sys-sub">被单据引用的单位不可删除，只能停用（历史单据需还原原始单位）</span>
      </div>
      </section>

    <!-- ==================== ② 税率 ==================== -->
    <section v-else-if="activeTab === 'tax'" class="sys-card">
      <div class="sys-card__head">
        <b class="sys-card__title">税率</b>
        <span class="sys-card__sub">启用 {{ enabledTaxes }} / {{ taxes.rows.length }}</span>
        <div class="sys-card__right">
        <el-button size="small" @click="openTaxCreate">+ 新增</el-button>
        </div>
      </div>

      <DataTable
        :data="taxes.rows"
        :columns="taxColumns"
        :card-fields="taxCardFields"
        card-title="label"
        :loading="taxes.loading"
        empty-text="暂无税率"
        :actions-width="150"
      >
        <template #label="{ row }">
          <span class="sys-strong">{{ row.label }}</span>
        </template>

        <template #rate="{ row }"><span class="sys-num">{{ row.rate }}</span></template>

        <template #is_default="{ row }">
          <StatusBadge v-if="row.is_default" label="默认" tone="brand" />
          <span v-else class="sys-sub">—</span>
        </template>

        <template #status="{ row }">
          <StatusBadge
            :label="row.status === 1 ? '启用' : '已停用'"
            :tone="row.status === 1 ? 'ok' : 'muted'"
          />
        </template>

        <template #card-extra="{ row }">
          <StatusBadge v-if="row.is_default" label="默认" tone="brand" />
        </template>

        <!-- DataTable 手机卡片按 `card-<slot||prop>` 取名，桌面插槽不会自动复用 -->
        <template #card-status="{ row }">
          <StatusBadge
            :label="row.status === 1 ? '启用' : '已停用'"
            :tone="row.status === 1 ? 'ok' : 'muted'"
          />
        </template>

        <template #actions="{ row }">
          <div class="sys-ops">
            <el-button link type="primary" @click="openTaxEdit(row)">编辑</el-button>
            <el-button link :type="row.status === 1 ? 'danger' : 'primary'" @click="toggleTax(row)">
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
          </div>
        </template>
        </DataTable>

        <div class="sys-card__foot">
        <span class="sys-sub">
          默认税率全站唯一 · 供货商报价时默认选中「默认」税率 · 默认项不可停用
        </span>
        </div>
      </section>

    <!-- ==================== ③ 供货商档案（全站唯一一处档案维护） ==================== -->
    <section v-else class="sys-card dict-page__archive">
      <div class="sys-card__head">
        <b class="sys-card__title">供货商档案</b>
        <span class="sys-card__sub">与账号一对一绑定 · 停用档案会同步停用绑定账号</span>
      </div>
      <div class="sys-card__body">
        <SupplierArchivePanel ref="archiveRef" active @create-account="onCreateAccountForArchive" />
      </div>
    </section>

    <!-- ==================== 新增 / 编辑计量单位 ==================== -->
    <el-dialog
      v-model="unitDialog.visible"
      :title="unitDialog.mode === 'create' ? '新增计量单位' : '编辑计量单位'"
      :width="isMobile ? '94%' : '440px'"
      :close-on-click-modal="false"
    >
      <el-form
        ref="unitFormRef"
        class="sys-form"
        :model="unitForm"
        :rules="unitRules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item label="单位名称" prop="name">
          <el-input v-model="unitForm.name" placeholder="如 个 / 台 / 千克" maxlength="20" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="unitForm.sort" :min="0" :max="9999" controls-position="right" />
          <div class="sys-field-hint">数字越小越靠前，控制下拉框中的显示顺序。</div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button class="dlg-btn" @click="unitDialog.visible = false">取消</el-button>
        <el-button class="dlg-btn" type="primary" :loading="unitDialog.submitting" @click="submitUnit">
          {{ unitDialog.mode === 'create' ? '新增' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 新增 / 编辑税率 ==================== -->
    <el-dialog
      v-model="taxDialog.visible"
      :title="taxDialog.mode === 'create' ? '新增税率' : '编辑税率'"
      :width="isMobile ? '94%' : '460px'"
      :close-on-click-modal="false"
    >
      <el-form
        ref="taxFormRef"
        class="sys-form"
        :model="taxForm"
        :rules="taxRules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item label="税率（%）" prop="percent">
          <el-input v-model="taxForm.percent" type="number" placeholder="如 13" @change="syncTaxLabel">
            <template #append>%</template>
          </el-input>
        </el-form-item>

        <el-form-item label="显示名" prop="label">
          <el-input v-model="taxForm.label" placeholder="如 13%" maxlength="20" />
        </el-form-item>

        <el-form-item label="排序">
          <el-input-number v-model="taxForm.sort" :min="0" :max="9999" controls-position="right" />
        </el-form-item>

        <el-form-item label="设为默认税率">
          <el-switch v-model="taxForm.is_default" />
          <div class="sys-field-hint">
            默认税率全站唯一：设为默认时后端会自动清除旧的默认项；供货商报价时默认选中该项。
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button class="dlg-btn" @click="taxDialog.visible = false">取消</el-button>
        <el-button class="dlg-btn" type="primary" :loading="taxDialog.submitting" @click="submitTax">
          {{ taxDialog.mode === 'create' ? '新增' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
@use './system-shared';
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

// 页签内容一次只显示一个卡片，占满整行（不再有并列网格）
.dict-page .sys-card {
  min-width: 0;
}

.dict-page__ref {
  margin-top: 2px;
  color: v.$warn;
}

.dict-page__archive {
  margin-top: 0;
}

.dlg-btn {
  @include bp.mobile {
    min-height: v.$touch-target;
    margin-left: v.$sp-2;
  }
}
</style>
