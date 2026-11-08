<script setup>
/**
 * EqChild — 设备管理 · 四类子台账通用页面（CH-014）
 * ---------------------------------------------------------------------------
 * 一个组件承载「动态事件 / 计量检定 / 特种检验 / 备件更换」四个页面，
 * 差异全部由 `eqConfig.js` 的 `CHILD_CONFIG[kind]` 描述（列、表单字段、提示语）。
 * kind 来自路由 meta（events/meters/specials/spares）。
 *
 * 强关联：新增时必须下拉选设备（后端按 asset_id 关联，不允许自由输入台账编号）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createEqChild,
  deleteEqChild,
  exportEq,
  getEqMeta,
  importEq,
  listEqAssets,
  listEqChildren,
  updateEqChild,
} from '@/api/equipment'
import { CHILD_CONFIG } from './eqConfig'

const route = useRoute()
const kind = computed(() => route.meta.childKind || 'events')
const config = computed(() => CHILD_CONFIG[kind.value])

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const meta = ref({})
const assets = ref([])
const query = reactive({ asset_id: null, status: '', event_type: '', page: 1, page_size: 20 })

const assetOptions = computed(() =>
  assets.value.map((a) => ({ value: a.id, label: `${a.asset_no} · ${a.name}` })),
)

async function load() {
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (query.asset_id) params.asset_id = query.asset_id
    if (kind.value === 'events' && query.event_type) params.event_type = query.event_type
    if ((kind.value === 'meters' || kind.value === 'specials') && query.status) params.status = query.status
    const data = await listEqChildren(kind.value, params)
    rows.value = data.items || []
    total.value = data.meta?.total || 0
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function loadAssets() {
  try {
    const data = await listEqAssets({ page: 1, page_size: 200 })
    assets.value = data.items || []
  } catch {
    assets.value = []
  }
}

function reset() {
  query.asset_id = null
  query.status = ''
  query.event_type = ''
  query.page = 1
  load()
}

// —— 表单 ——
const dialog = reactive({ visible: false, saving: false, mode: 'create', form: {} })

function emptyForm() {
  const form = {}
  config.value.fields.forEach((f) => {
    form[f.prop] = f.type === 'switch' ? true : f.type === 'number' ? null : ''
  })
  if (kind.value === 'meters') form.status = '在用'
  if (kind.value === 'specials') form.status = '在用'
  if (query.asset_id) form.asset_id = query.asset_id
  return form
}

function openCreate() {
  dialog.mode = 'create'
  dialog.form = emptyForm()
  dialog.visible = true
}

function openEdit(row) {
  dialog.mode = 'edit'
  const form = emptyForm()
  Object.keys(form).forEach((k) => {
    if (row[k] !== null && row[k] !== undefined) form[k] = row[k]
  })
  form.id = row.id
  dialog.form = form
  dialog.visible = true
}

function optionsOf(field) {
  if (field.optionsKey) return meta.value[field.optionsKey] || []
  return []
}

async function submit() {
  const missing = config.value.fields.filter(
    (f) => f.required && (dialog.form[f.prop] === '' || dialog.form[f.prop] === null || dialog.form[f.prop] === undefined),
  )
  if (missing.length) return ElMessage.warning(`请填写「${missing[0].label}」`)
  dialog.saving = true
  try {
    const payload = { ...dialog.form }
    delete payload.id
    payload.asset_id = Number(payload.asset_id)
    config.value.fields.forEach((f) => {
      if (f.type === 'number') {
        payload[f.prop] = payload[f.prop] === '' || payload[f.prop] === null ? null : String(payload[f.prop])
      }
    })
    if (dialog.mode === 'create') {
      await createEqChild(kind.value, payload)
      ElMessage.success('已新增')
    } else {
      await updateEqChild(kind.value, dialog.form.id, payload)
      ElMessage.success('已保存')
    }
    dialog.visible = false
    load()
  } catch {
    /* 已提示 */
  } finally {
    dialog.saving = false
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(`删除这条「${config.value.title}」记录？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteEqChild(kind.value, row.id)
    ElMessage.success('已删除')
    load()
  } catch {
    /* 取消或后端拒绝 */
  }
}

// —— 导入导出 ——
const importDlg = reactive({ visible: false, running: false, result: null })
const fileInput = ref(null)

async function onFileChange(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importDlg.running = true
  try {
    importDlg.result = await importEq(kind.value, file)
    const r = importDlg.result
    if (r.failed) ElMessage.warning(`导入完成：成功 ${r.created} 行，失败 ${r.failed} 行`)
    else ElMessage.success(`导入成功 ${r.created} 行`)
    load()
  } catch {
    /* 已提示 */
  } finally {
    importDlg.running = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function openImport() {
  importDlg.result = null
  importDlg.visible = true
}

async function doExport() {
  try {
    await exportEq(kind.value, `${config.value.title}.xlsx`)
  } catch {
    /* 已提示 */
  }
}

// —— 渲染辅助 ——
function dayClass(row) {
  const days = row.days_to_expire ?? row.days_to_plan
  if (days === null || days === undefined) return ''
  if (days < 0) return 'is-over'
  if (days <= 15) return 'is-warn'
  return ''
}

function fmtDate(value) {
  return value ? String(value).slice(0, 10) : '—'
}

onMounted(async () => {
  try {
    meta.value = await getEqMeta()
  } catch {
    /* 已提示 */
  }
  await loadAssets()
  load()
})
</script>

<template>
  <div class="eq-child">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">{{ config.title }}</h2>
        <p class="page-head__sub">{{ config.hint }}</p>
      </div>
      <div class="page-head__actions">
        <el-button size="small" @click="openImport">导入 Excel</el-button>
        <el-button size="small" @click="doExport">导出 Excel</el-button>
        <el-button size="small" type="primary" @click="openCreate">+ 新增记录</el-button>
      </div>
    </header>

    <section class="card filter-bar">
      <el-select
        v-model="query.asset_id"
        placeholder="按设备筛选"
        clearable
        filterable
        style="width: 260px"
      >
        <el-option v-for="o in assetOptions" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-select v-if="kind === 'events'" v-model="query.event_type" placeholder="事件类型" clearable style="width: 150px">
        <el-option v-for="t in meta.event_types || []" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select
        v-if="kind === 'meters' || kind === 'specials'"
        v-model="query.status"
        placeholder="状态"
        clearable
        style="width: 130px"
      >
        <el-option
          v-for="s in (kind === 'meters' ? meta.meter_status : meta.special_status) || []"
          :key="s"
          :label="s"
          :value="s"
        />
      </el-select>
      <el-button type="primary" size="small" @click="query.page = 1; load()">查询</el-button>
      <el-button size="small" @click="reset">重置</el-button>
    </section>

    <section v-loading="loading" class="card">
      <el-table :data="rows" border size="small" style="width: 100%" row-key="id">
        <el-table-column
          v-for="col in config.columns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :width="col.width"
          :min-width="col.minWidth"
          :show-overflow-tooltip="!!col.showOverflow"
        >
          <template #default="{ row }">
            <span v-if="col.kind === 'date'">{{ fmtDate(row[col.prop]) }}</span>
            <span v-else-if="col.kind === 'days'" :class="['num', dayClass(row)]">
              {{ row[col.daysOf] ?? '—' }}
            </span>
            <span v-else-if="col.kind === 'bool'">{{ row[col.prop] ? '是' : '否' }}</span>
            <span v-else-if="col.kind === 'tag'" class="badge badge--brand">{{ row[col.prop] }}</span>
            <span v-else-if="col.kind === 'money'">{{ row[col.prop] ?? '—' }}</span>
            <span v-else-if="col.kind === 'asset'" class="num">{{ row[col.prop] || '—' }}</span>
            <span v-else>{{ row[col.prop] ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">
            暂无记录。点「+ 新增记录」登记，或先到「设备台账」建档后再导入。
          </div>
        </template>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="query.page = 1; load()"
        />
      </div>
    </section>

    <!-- 新增/编辑 -->
    <el-dialog
      v-model="dialog.visible"
      :title="`${dialog.mode === 'create' ? '新增' : '编辑'} · ${config.title}`"
      width="820px"
      :close-on-click-modal="false"
    >
      <el-form label-width="118px">
        <el-row :gutter="12">
          <el-col v-for="f in config.fields" :key="f.prop" :span="f.span || 12">
            <el-form-item :label="f.label" :required="f.required">
              <el-select
                v-if="f.type === 'asset'"
                v-model="dialog.form[f.prop]"
                filterable
                placeholder="选择设备（台账编号 · 名称）"
                style="width: 100%"
              >
                <el-option v-for="o in assetOptions" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-input
                v-else-if="f.type === 'input'"
                v-model="dialog.form[f.prop]"
                :placeholder="f.placeholder"
                clearable
              />
              <el-input
                v-else-if="f.type === 'textarea'"
                v-model="dialog.form[f.prop]"
                type="textarea"
                :rows="2"
              />
              <el-date-picker
                v-else-if="f.type === 'date'"
                v-model="dialog.form[f.prop]"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
              <el-select
                v-else-if="f.type === 'select'"
                v-model="dialog.form[f.prop]"
                clearable
                style="width: 100%"
              >
                <el-option v-for="o in optionsOf(f)" :key="o" :label="o" :value="o" />
              </el-select>
              <el-switch v-else-if="f.type === 'switch'" v-model="dialog.form[f.prop]" />
              <el-input
                v-else-if="f.type === 'number'"
                v-model="dialog.form[f.prop]"
                :placeholder="f.placeholder"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入 -->
    <el-dialog v-model="importDlg.visible" :title="`导入 · ${config.title}`" width="560px">
      <p class="dialog-tip">
        按模板列名读取；「台账编号」必须已存在于设备台账（强关联），否则该行失败并说明原因。
      </p>
      <input ref="fileInput" type="file" accept=".xlsx" @change="onFileChange" />
      <p v-if="importDlg.running" class="import-running">正在导入，请稍候…</p>
      <div v-if="importDlg.result" class="import-result">
        <p>
          共 {{ importDlg.result.total }} 行，成功 <b class="ok">{{ importDlg.result.created }}</b> 行，
          失败 <b class="bad">{{ importDlg.result.failed }}</b> 行
        </p>
        <el-table v-if="importDlg.result.errors?.length" :data="importDlg.result.errors" border size="small" max-height="220">
          <el-table-column prop="row" label="行号" width="70" />
          <el-table-column prop="reason" label="失败原因" />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="importDlg.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.eq-child {
  display: flex;
  flex-direction: column;
  gap: v.$sp-4;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
}

.page-head__title {
  margin: 0;
  font-size: v.$fs-title;
}

.page-head__sub {
  margin: 3px 0 0;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.page-head__actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.card {
  padding: v.$sp-3;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: v.$fs-xs;
  background: v.$brand-50;
  color: v.$brand-800;
}

.num {
  font-family: v.$font-num;
}

.is-warn {
  color: v.$warn;
  font-weight: 600;
}

.is-over {
  color: v.$danger;
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: v.$sp-3;
}

.dialog-tip {
  margin: 0 0 v.$sp-3;
  padding: v.$sp-2 v.$sp-3;
  background: v.$surface-sunken;
  border-radius: v.$r-sm;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.import-running {
  color: v.$brand-700;
  font-size: v.$fs-sm;
}

.import-result {
  margin-top: v.$sp-3;
  font-size: v.$fs-sm;

  .ok { color: v.$ok; }
  .bad { color: v.$danger; }
}

.empty-text {
  padding: v.$sp-3 0;
  color: v.$ink-400;
  font-size: v.$fs-sm;
  text-align: center;
}

@include bp.mobile {
  .page-head {
    flex-direction: column;
  }

  .page-head__actions {
    margin-left: 0;
    width: 100%;
  }

  .card {
    overflow-x: auto;
  }
}
</style>
