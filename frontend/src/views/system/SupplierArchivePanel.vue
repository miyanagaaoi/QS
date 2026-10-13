<script setup>
/**
 * SupplierArchivePanel — 供货商档案维护（PRD FR-MST-03 / FR-MST-04，设计稿 04-3 下半个卡片）
 * ---------------------------------------------------------------------------
 * 被两处复用：
 *   1. /system/account 的「供货商档案」页签（AccountList.vue）
 *   2. /system/dict 的基础字典页（DictList.vue）
 * 因此做成独立面板组件，避免同一份表格逻辑写两遍。
 *
 * 关键约束：
 *  - 名称唯一；档案停用会**同步停用其绑定账号**，启用档案不自动启用账号（后端 message 已说明）；
 *  - 未绑定账号的档案行显示「新建账号」入口（emit create-account，由父组件打开新建弹窗）；
 *  - 后端没有"删除档案"接口，只有停用（历史单据需保留）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DataTable from '@/components/DataTable.vue'
import FilterDrawer from '@/components/FilterDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useBreakpoint } from '@/composables/useBreakpoint'

import * as api from './adminApi'

defineOptions({ name: 'SupplierArchivePanel' })

const props = defineProps({
  /** 父组件用页签承载时为 true；DictList 常驻为 true */
  active: { type: Boolean, default: true },
})
const emit = defineEmits(['create-account', 'changed'])

const { isMobile } = useBreakpoint()

const state = reactive({
  loading: false,
  rows: [],
  page: 1,
  pageSize: 20,
  total: 0,
  query: { keyword: '', status: '' },
})

const columns = [
  { prop: 'name', label: '供货商名称', width: 170 },
  { prop: 'credit_code', label: '统一社会信用代码', width: 180, num: true, hiddenOn: ['tablet'] },
  { prop: 'contact_name', label: '联系人', width: 100 },
  { prop: 'contact_phone', label: '联系电话', width: 135, num: true },
  { prop: 'contact_email', label: '邮箱', width: 185, hiddenOn: ['tablet'] },
  { prop: 'account_username', label: '绑定账号', width: 130 },
  { prop: 'status', label: '状态', width: 100 },
]

// 手机卡片：状态以标题右侧徽标呈现，避免与字段重复
const cardFields = [
  { label: '信用代码', prop: 'credit_code', num: true },
  { label: '联系人', prop: 'contact_name' },
  { label: '电话', prop: 'contact_phone', num: true },
  { label: '绑定账号', prop: 'account_username', slot: 'account_username' },
]

const filterCount = computed(
  () => Object.values(state.query).filter((value) => value !== '' && value !== null).length,
)

async function load() {
  state.loading = true
  try {
    const params = { page: state.page, page_size: state.pageSize }
    if (state.query.keyword.trim()) params.keyword = state.query.keyword.trim()
    if (state.query.status !== '') params.status = Number(state.query.status)
    const data = await api.listSuppliers(params)
    state.rows = data?.items || []
    state.total = Number(data?.meta?.total || 0)
  } catch {
    state.rows = []
    state.total = 0
  } finally {
    state.loading = false
  }
}

function search() {
  state.page = 1
  load()
}

function resetFilter() {
  state.query.keyword = ''
  state.query.status = ''
  search()
}

function onPage({ page, pageSize }) {
  state.page = page
  if (pageSize) state.pageSize = pageSize
  load()
}

// —— 新增 / 编辑档案 ——
const dialog = reactive({ visible: false, mode: 'create', submitting: false })
const formRef = ref(null)
const form = reactive({
  id: null,
  name: '',
  credit_code: '',
  contact_name: '',
  contact_phone: '',
  contact_email: '',
  address: '',
  remark: '',
})

const rules = {
  name: [
    { required: true, message: '请输入供货商名称', trigger: 'blur' },
    { max: 100, message: '名称最长 100 个字符', trigger: 'blur' },
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

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    credit_code: '',
    contact_name: '',
    contact_phone: '',
    contact_email: '',
    address: '',
    remark: '',
  })
  dialog.mode = 'create'
  dialog.visible = true
  formRef.value?.clearValidate?.()
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name || '',
    credit_code: row.credit_code || '',
    contact_name: row.contact_name || '',
    contact_phone: row.contact_phone || '',
    contact_email: row.contact_email || '',
    address: row.address || '',
    remark: row.remark || '',
  })
  dialog.mode = 'edit'
  dialog.visible = true
  formRef.value?.clearValidate?.()
}

async function submit() {
  const instance = formRef.value
  if (!instance) return
  try {
    await instance.validate()
  } catch {
    return
  }

  dialog.submitting = true
  const payload = {
    name: form.name.trim(),
    credit_code: form.credit_code.trim() || null,
    contact_name: form.contact_name.trim() || null,
    contact_phone: form.contact_phone.trim() || null,
    contact_email: form.contact_email.trim() || null,
    address: form.address.trim() || null,
    remark: form.remark.trim() || null,
  }
  try {
    if (dialog.mode === 'create') {
      await api.createSupplier(payload)
      ElMessage.success('供货商档案已创建')
    } else {
      await api.updateSupplier(form.id, payload)
      ElMessage.success('供货商档案已保存')
    }
    dialog.visible = false
    await load()
    emit('changed')
  } catch (error) {
    // 名称唯一冲突 → 后端 409 原文
    if (error?.code === 40900 || error?.status === 409) {
      ElMessageBox.alert(String(error.message || '保存被系统拒绝'), '无法保存供货商档案', {
        type: 'error',
        confirmButtonText: '我知道了',
      }).catch(() => {})
    }
  } finally {
    dialog.submitting = false
  }
}

async function toggle(row) {
  const turningOff = row.status === 1
  const bound = row.account_username ? `，其绑定账号「${row.account_username}」也会被同步停用` : ''
  try {
    await ElMessageBox.confirm(
      turningOff
        ? `停用后该档案将不再出现在新的询价单邀请范围中${bound}；历史询价单与报价数据完整保留。启用档案不会自动启用绑定账号，需要单独启用。`
        : '启用后该档案可重新被邀请报价；其绑定账号需要单独启用。',
      turningOff ? '确认停用该供货商档案？' : '确认启用该供货商档案？',
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
    const data = await api.toggleSupplierStatus(row.id)
    ElMessage.success(data?.message || (turningOff ? '档案已停用' : '档案已启用'))
    await load()
    emit('changed')
  } catch (error) {
    ElMessageBox.alert(String(error?.message || '操作被系统拒绝，请稍后重试'), '无法变更档案状态', {
      type: 'error',
      confirmButtonText: '我知道了',
    }).catch(() => {})
  }
}

function exportList() {
  // 后端未提供档案导出接口 → 前端 CSV 兜底（Excel 可直接打开）
  api.downloadCsv(
    `供货商档案_${api.dateStamp()}.csv`,
    [
      { key: 'name', label: '供货商名称' },
      { key: 'credit_code', label: '统一社会信用代码' },
      { key: 'contact_name', label: '联系人' },
      { key: 'contact_phone', label: '联系电话' },
      { key: 'contact_email', label: '邮箱' },
      { key: 'address', label: '地址' },
      { key: 'account_username', label: '绑定账号' },
      { key: 'status_text', label: '状态' },
      { key: 'created_at', label: '创建时间' },
    ],
    state.rows.map((row) => ({ ...row, status_text: row.status === 1 ? '启用' : '已停用' })),
  )
  ElMessage.success(
    isMobile.value ? '文件已开始下载，建议在电脑上查看' : '已导出本页供货商档案（CSV）',
  )
}

/** 父组件（AccountList）需要感知档案总数变化时由本组件触发 */
function refresh() {
  return load()
}

defineExpose({ refresh })

onMounted(() => {
  if (props.active) load()
})

watch(
  () => props.active,
  (active) => {
    if (active) load()
  },
)
</script>

<template>
  <section class="archive-panel">
    <div class="archive-panel__bar">
      <div class="archive-panel__count">
        共 <span class="sys-num">{{ state.total }}</span> 家供货商档案 · 与账号一对一绑定
      </div>
      <div class="archive-panel__actions">
        <el-button @click="exportList">导出</el-button>
        <el-button type="primary" @click="openCreate">+ 新增档案</el-button>
      </div>
    </div>

    <FilterDrawer
      :active-count="filterCount"
      :loading="state.loading"
      @search="search"
      @reset="resetFilter"
    >
      <el-form-item label="名称 / 联系人 / 电话">
        <el-input
          v-model="state.query.keyword"
          class="f-field"
          placeholder="名称、联系人或电话"
          clearable
          @keyup.enter="search"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="state.query.status" class="f-field" placeholder="全部状态" clearable>
          <el-option label="启用" value="1" />
          <el-option label="停用" value="0" />
        </el-select>
      </el-form-item>
    </FilterDrawer>

    <DataTable
      :data="state.rows"
      :columns="columns"
      :card-fields="cardFields"
      card-title="name"
      :loading="state.loading"
      :pagination="{ page: state.page, pageSize: state.pageSize, total: state.total }"
      empty-text="暂无供货商档案"
      :actions-width="210"
      @page-change="onPage"
    >
      <template #name="{ row }">
        <span class="sys-strong">{{ row.name }}</span>
        <div v-if="row.status === 0" class="sys-sub">已停止合作</div>
      </template>

      <template #credit_code="{ row }">
        <span class="sys-num sys-sub">{{ row.credit_code || '—' }}</span>
      </template>
      <template #contact_phone="{ row }">
        <span class="sys-num">{{ row.contact_phone || '—' }}</span>
      </template>
      <template #contact_email="{ row }">
        <span class="sys-sub">{{ row.contact_email || '—' }}</span>
      </template>

      <template #account_username="{ row }">
        <StatusBadge
          v-if="row.account_bound"
          :label="row.account_username || '已绑定'"
          :tone="row.status === 1 ? 'ok' : 'muted'"
        />
        <StatusBadge v-else label="未绑定账号" tone="warn" />
      </template>

      <template #status="{ row }">
        <StatusBadge
          :label="row.status === 1 ? '启用' : '已停用'"
          :tone="row.status === 1 ? 'ok' : 'muted'"
        />
      </template>

      <template #card-extra="{ row }">
        <StatusBadge
          :label="row.status === 1 ? '启用' : '已停用'"
          :tone="row.status === 1 ? 'ok' : 'muted'"
        />
      </template>

      <!-- DataTable 手机卡片按 `card-<slot||prop>` 取名，桌面插槽不会自动复用。
           已绑定账号是较长的登录名（如 hengxin_wenju），手机端用等宽文本而不是徽标，
           避免 nowrap 胶囊撑破卡片（375px 实测）。 -->
      <template #card-account_username="{ row }">
        <span v-if="row.account_bound" class="sys-num">{{ row.account_username || '已绑定' }}</span>
        <StatusBadge v-else label="未绑定账号" tone="warn" />
      </template>

      <template #actions="{ row }">
        <div class="sys-ops">
          <el-button v-if="!row.account_bound" link type="primary" @click="emit('create-account', row)">
            新建账号
          </el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link :type="row.status === 1 ? 'danger' : 'primary'" @click="toggle(row)">
            {{ row.status === 1 ? '停用' : '启用' }}
          </el-button>
        </div>
      </template>
    </DataTable>

    <div class="sys-alert sys-alert--info archive-panel__note">
      <span class="sys-alert__icon">i</span>
      <div>
        <b>档案与账号一对一：</b>未绑定账号的档案会显示「新建账号」入口；
        <b>停用档案会同步停用其绑定账号</b>（启用档案不会自动启用账号）。档案只可停用，不可删除。
      </div>
    </div>

    <!-- 新增 / 编辑档案 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'create' ? '新增供货商档案' : '编辑供货商档案'"
      :width="isMobile ? '94%' : '640px'"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        class="sys-form"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item label="供货商名称" prop="name">
          <el-input v-model="form.name" placeholder="营业执照名称（唯一）" maxlength="100" />
        </el-form-item>
        <div class="grid2">
          <el-form-item label="统一社会信用代码">
            <el-input v-model="form.credit_code" placeholder="可空" maxlength="30" />
          </el-form-item>
          <el-form-item label="联系人">
            <el-input v-model="form.contact_name" placeholder="可空" maxlength="50" />
          </el-form-item>
          <el-form-item label="联系电话" prop="contact_phone">
            <el-input v-model="form.contact_phone" placeholder="手机号或座机" maxlength="30" />
          </el-form-item>
          <el-form-item label="邮箱" prop="contact_email">
            <el-input v-model="form.contact_email" placeholder="可空" maxlength="100" />
          </el-form-item>
        </div>
        <el-form-item label="地址">
          <el-input v-model="form.address" placeholder="可空" maxlength="200" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button class="dlg-btn" @click="dialog.visible = false">取消</el-button>
        <el-button class="dlg-btn" type="primary" :loading="dialog.submitting" @click="submit">
          {{ dialog.mode === 'create' ? '创建档案' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
@use './system-shared';
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.archive-panel__bar {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
  margin-bottom: v.$sp-3;
}

.archive-panel__count {
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.archive-panel__actions {
  display: flex;
  gap: v.$sp-2;

  @include bp.mobile {
    // 极窄视口（如 320px）下允许换行，避免两个按钮挤出容器
    flex-wrap: wrap;
    width: 100%;

    .el-button {
      flex: 1 1 140px;
      min-height: v.$touch-target;
      margin-left: 0;
    }
  }

  @include bp.tablet-up {
    margin-left: auto;
  }
}

.archive-panel__note {
  margin-top: v.$sp-3;
  margin-bottom: 0;
}

.f-field {
  width: 100%;
}

@include bp.tablet-up {
  .f-field {
    width: 220px;
  }
}

.grid2 {
  display: grid;
  gap: 0 v.$sp-3;

  @include bp.tablet-up {
    grid-template-columns: 1fr 1fr;
  }
}

.dlg-btn {
  @include bp.mobile {
    min-height: v.$touch-target;
    margin-left: v.$sp-2;
  }
}
</style>
