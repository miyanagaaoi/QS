<script setup>
/**
 * EqAssets — 设备管理 · 设备主台账（CH-014）
 * ---------------------------------------------------------------------------
 * 一台设备一行；四类子台账（动态事件/计量检定/特种检验/备件更换）在详情抽屉里查看。
 * 预警色：距质保到期 ≤30 天标橙、<0 天标红（与 Excel 模板规则一致）。
 * 删除设备前必须先删子记录（后端 409 会提示具体条数）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createEqAsset,
  deleteEqAsset,
  downloadEqTemplate,
  exportEq,
  getEqAsset,
  getEqMeta,
  importEq,
  listEqAssets,
  updateEqAsset,
} from '@/api/equipment'
import { ASSET_COLUMNS, ASSET_FORM_FIELDS, ASSET_STATUS_TONE } from './eqConfig'

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const meta = ref({ importance: [], asset_status: [] })
const query = reactive({ keyword: '', status: '', category: '', importance: '', page: 1, page_size: 20 })

const categories = computed(() => [...new Set(rows.value.map((r) => r.category).filter(Boolean))])

async function load() {
  loading.value = true
  try {
    const data = await listEqAssets({
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      category: query.category || undefined,
      importance: query.importance || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = data.items || []
    total.value = data.meta?.total || 0
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reset() {
  query.keyword = ''
  query.status = ''
  query.category = ''
  query.importance = ''
  query.page = 1
  load()
}

// —— 表单 ——
const dialog = reactive({ visible: false, saving: false, mode: 'create', form: {} })

function emptyForm() {
  const form = {}
  ASSET_FORM_FIELDS.forEach((f) => {
    form[f.prop] = f.type === 'switch' ? false : f.type === 'number' ? null : ''
  })
  form.status = '在用'
  form.is_special = false
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
    form[k] = row[k] === null || row[k] === undefined ? form[k] : row[k]
  })
  form.id = row.id
  dialog.form = form
  dialog.visible = true
}

function fieldOptions(field) {
  if (field.type === 'asset') return []
  if (field.optionsKey) return meta.value[field.optionsKey] || []
  return []
}

async function submit() {
  const required = ASSET_FORM_FIELDS.filter((f) => f.required && !String(dialog.form[f.prop] ?? '').trim())
  if (required.length) return ElMessage.warning(`请填写「${required[0].label}」`)
  if (dialog.form.is_special && !String(dialog.form.special_reg_no ?? '').trim()) {
    return ElMessage.warning('特种设备必须填写特种设备登记号')
  }
  dialog.saving = true
  try {
    const payload = { ...dialog.form }
    delete payload.id
    payload.is_special = Boolean(payload.is_special)
    ;['design_life_years'].forEach((k) => {
      if (payload[k] === '' || payload[k] === null || payload[k] === undefined) payload[k] = null
      else payload[k] = Number(payload[k])
    })
    payload.purchase_value =
      payload.purchase_value === '' || payload.purchase_value === null ? null : String(payload.purchase_value)
    if (dialog.mode === 'create') {
      await createEqAsset(payload)
      ElMessage.success('设备已建档')
    } else {
      await updateEqAsset(dialog.form.id, payload)
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
    await ElMessageBox.confirm(
      `删除设备「${row.name}（${row.asset_no}）」？有子台账记录时不允许删除。`,
      '删除设备',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteEqAsset(row.id)
    ElMessage.success('已删除')
    load()
  } catch {
    /* 取消或后端拒绝 */
  }
}

// —— 详情抽屉 ——
const detail = reactive({ visible: false, loading: false, data: null, tab: 'events' })

async function openDetail(row) {
  detail.visible = true
  detail.loading = true
  detail.data = null
  detail.tab = 'events'
  try {
    detail.data = await getEqAsset(row.id)
  } catch {
    /* 已提示 */
  } finally {
    detail.loading = false
  }
}

// —— 导入 / 导出 ——
const importDlg = reactive({ visible: false, running: false, result: null, fileName: '' })
const fileInput = ref(null)

function openImport() {
  importDlg.result = null
  importDlg.fileName = ''
  importDlg.visible = true
}

async function onFileChange(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importDlg.fileName = file.name
  importDlg.running = true
  try {
    importDlg.result = await importEq('assets', file)
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

async function doExport() {
  try {
    await exportEq('assets', '设备主台账.xlsx')
  } catch {
    /* 已提示 */
  }
}

async function doTemplate() {
  try {
    await downloadEqTemplate()
  } catch {
    /* 已提示 */
  }
}

function tone(value, dayField, warnDays) {
  if (value === null || value === undefined) return ''
  if (dayField !== undefined) {
    if (value < 0) return 'is-over'
    if (value <= (warnDays ?? 15)) return 'is-warn'
    return ''
  }
  return ''
}

function fmtDate(value) {
  return value ? String(value).slice(0, 10) : '—'
}

function dayClass(row, col) {
  const days = row[col.daysOf]
  if (days === null || days === undefined) return ''
  if (days < 0) return 'is-over'
  if (days <= (col.warnDays ?? 15)) return 'is-warn'
  return ''
}

function childCount(row) {
  return (row.event_count || 0) + (row.meter_count || 0) + (row.special_count || 0) + (row.spare_count || 0)
}

const CHILD_TABS = [
  { key: 'events', label: '动态事件' },
  { key: 'meters', label: '计量检定' },
  { key: 'specials', label: '特种检验' },
  { key: 'spares', label: '备件更换' },
]

onMounted(async () => {
  try {
    meta.value = await getEqMeta()
  } catch {
    /* 已提示 */
  }
  load()
})
</script>

<template>
  <div class="eq-assets">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">设备台账</h2>
        <p class="page-head__sub">
          设备全生命周期管理台账 · 一台设备一行 · 质保 ≤30 天标橙、超期标红
        </p>
      </div>
      <div class="page-head__actions">
        <el-button size="small" @click="doTemplate">导入模板</el-button>
        <el-button size="small" @click="openImport">导入 Excel</el-button>
        <el-button size="small" @click="doExport">导出 Excel</el-button>
        <el-button size="small" type="primary" @click="openCreate">+ 新增设备</el-button>
      </div>
    </header>

    <section class="card filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="台账编号 / 资产编号 / 名称 / 地点 / 责任人"
        clearable
        style="width: 280px"
        @keyup.enter="query.page = 1; load()"
      />
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px">
        <el-option v-for="s in meta.asset_status || []" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="query.category" placeholder="类别" clearable style="width: 140px">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="query.importance" placeholder="等级" clearable style="width: 110px">
        <el-option v-for="i in meta.importance || []" :key="i" :label="`${i} 级`" :value="i" />
      </el-select>
      <el-button type="primary" size="small" @click="query.page = 1; load()">查询</el-button>
      <el-button size="small" @click="reset">重置</el-button>
    </section>

    <section v-loading="loading" class="card">
      <el-table :data="rows" border size="small" style="width: 100%" row-key="id">
        <el-table-column
          v-for="col in ASSET_COLUMNS"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :width="col.width"
          :min-width="col.minWidth"
          :show-overflow-tooltip="!!col.showOverflow"
        >
          <template #default="{ row }">
            <button v-if="col.kind === 'asset'" class="link" type="button" @click="openDetail(row)">
              {{ row.asset_no }}
            </button>
            <span
              v-else-if="col.kind === 'status'"
              :class="['badge', `badge--${ASSET_STATUS_TONE[row.status] || 'muted'}`]"
            >
              {{ row.status }}
            </span>
            <span v-else-if="col.kind === 'badge'" class="badge badge--brand">{{ row.importance || '—' }}</span>
            <span v-else-if="col.kind === 'date'">{{ fmtDate(row[col.prop]) }}</span>
            <span v-else-if="col.kind === 'days'" :class="['num', dayClass(row, col)]">
              {{ row[col.daysOf] ?? '—' }}
            </span>
            <span v-else-if="col.kind === 'childCount'" class="child-count">{{ childCount(row) }}</span>
            <span v-else-if="col.kind === 'money'">{{ row[col.prop] ?? '—' }}</span>
            <span v-else>{{ row[col.prop] ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">暂无设备，点右上「+ 新增设备」或「导入 Excel」建档</div>
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
      :title="dialog.mode === 'create' ? '新增设备' : '编辑设备'"
      width="880px"
      :close-on-click-modal="false"
    >
      <el-form label-width="118px">
        <el-row :gutter="12">
          <el-col v-for="f in ASSET_FORM_FIELDS" :key="f.prop" :span="f.span || 12">
            <el-form-item :label="f.label" :required="f.required">
              <el-input
                v-if="f.type === 'input'"
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
                <el-option v-for="o in fieldOptions(f)" :key="o" :label="o" :value="o" />
              </el-select>
              <el-switch v-else-if="f.type === 'switch'" v-model="dialog.form[f.prop]" />
              <el-input v-else-if="f.type === 'number'" v-model="dialog.form[f.prop]" :placeholder="f.placeholder" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情 -->
    <el-drawer v-model="detail.visible" :title="detail.data ? `${detail.data.name}（${detail.data.asset_no}）` : '设备详情'" size="720px">
      <div v-loading="detail.loading">
        <template v-if="detail.data">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="台账编号">{{ detail.data.asset_no }}</el-descriptions-item>
            <el-descriptions-item label="资产编号">{{ detail.data.finance_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="规格型号">{{ detail.data.model || '—' }}</el-descriptions-item>
            <el-descriptions-item label="类别 / 等级">
              {{ detail.data.category || '—' }} / {{ detail.data.importance || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="安装地点">{{ detail.data.location || '—' }}</el-descriptions-item>
            <el-descriptions-item label="所属系统">{{ detail.data.system_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="当前状态">
              <span :class="['badge', `badge--${ASSET_STATUS_TONE[detail.data.status] || 'muted'}`]">
                {{ detail.data.status }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="属地责任人">{{ detail.data.owner || '—' }}</el-descriptions-item>
            <el-descriptions-item label="投用日期">{{ fmtDate(detail.data.commission_date) }}</el-descriptions-item>
            <el-descriptions-item label="质保期">
              {{ fmtDate(detail.data.warranty_start) }} ~ {{ fmtDate(detail.data.warranty_end) }}
            </el-descriptions-item>
            <el-descriptions-item label="距质保到期">
              <span :class="['num', (detail.data.days_to_warranty ?? 999) < 0 ? 'is-over' : (detail.data.days_to_warranty ?? 999) <= 30 ? 'is-warn' : '']">
                {{ detail.data.days_to_warranty ?? '—' }} 天
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="是否特种设备">
              {{ detail.data.is_special ? `是（${detail.data.special_reg_no || '未填登记号'}）` : '否' }}
            </el-descriptions-item>
            <el-descriptions-item label="设计使用年限">{{ detail.data.design_life_years ?? '—' }} 年</el-descriptions-item>
            <el-descriptions-item label="预计报废日期">{{ fmtDate(detail.data.scrap_date) }}</el-descriptions-item>
            <el-descriptions-item label="采购原值">{{ detail.data.purchase_value ?? '—' }} 元</el-descriptions-item>
            <el-descriptions-item label="供应商">{{ detail.data.supplier || '—' }}</el-descriptions-item>
            <el-descriptions-item label="备注" :span="2">{{ detail.data.remark || '—' }}</el-descriptions-item>
          </el-descriptions>

          <el-tabs v-model="detail.tab" class="detail-tabs">
            <el-tab-pane
              v-for="tab in CHILD_TABS"
              :key="tab.key"
              :label="`${tab.label}（${detail.data[tab.key].length}）`"
              :name="tab.key"
            >
              <el-table :data="detail.data[tab.key]" border size="small" max-height="320">
                <template v-if="tab.key === 'events'">
                  <el-table-column prop="event_type" label="类型" width="100" />
                  <el-table-column prop="occur_date" label="发生" width="102" />
                  <el-table-column prop="actual_date" label="完成" width="102" />
                  <el-table-column prop="content" label="简述" min-width="160" show-overflow-tooltip />
                  <el-table-column prop="accept_result" label="验收" width="80" />
                </template>
                <template v-else-if="tab.key === 'meters'">
                  <el-table-column prop="name" label="器具" min-width="120" />
                  <el-table-column prop="valid_until" label="有效期至" width="106" />
                  <el-table-column prop="days_to_expire" label="距到期" width="80" />
                  <el-table-column prop="status" label="状态" width="80" />
                </template>
                <template v-else-if="tab.key === 'specials'">
                  <el-table-column prop="check_type" label="检验类型" width="100" />
                  <el-table-column prop="valid_until" label="有效期至" width="106" />
                  <el-table-column prop="days_to_expire" label="距到期" width="80" />
                  <el-table-column prop="reg_no" label="注册编号" min-width="120" />
                </template>
                <template v-else>
                  <el-table-column prop="part_name" label="备件" min-width="120" />
                  <el-table-column prop="replace_date" label="更换" width="102" />
                  <el-table-column prop="qty" label="数量" width="70" />
                  <el-table-column prop="amount" label="金额" width="90" />
                  <el-table-column prop="old_disposal" label="旧件处置" width="100" />
                </template>
                <template #empty><div class="empty-text">暂无记录</div></template>
              </el-table>
            </el-tab-pane>
          </el-tabs>

          <div class="detail-actions">
            <el-button size="small" @click="router.push('/eq/events')">去登记动态事件</el-button>
            <el-button size="small" @click="detail.visible = false">关闭</el-button>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 导入 -->
    <el-dialog v-model="importDlg.visible" title="导入设备台账（Excel）" width="560px">
      <p class="dialog-tip">
        按模板列名读取（列顺序无关）。台账编号重复或必填缺失的行会失败并列出原因，其余行照常导入。
        先下载「导入模板」填写最省事。
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

.eq-assets {
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

.link {
  padding: 0;
  border: none;
  background: none;
  color: v.$brand-700;
  font-size: v.$fs-sm;
  font-family: v.$font-num;
  cursor: pointer;

  &:hover {
    text-decoration: underline;
  }
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: v.$fs-xs;
  border: 1px solid transparent;
}

.badge--brand { background: v.$brand-50; color: v.$brand-800; border-color: v.$brand-100; }
.badge--ok { background: v.$ok-bg; color: v.$ok; border-color: v.$ok-line; }
.badge--warn { background: v.$warn-bg; color: v.$warn; border-color: v.$warn-line; }
.badge--danger { background: v.$danger-bg; color: v.$danger; border-color: v.$danger-line; }
.badge--muted { background: v.$muted-bg; color: v.$muted; border-color: v.$muted-line; }

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

.child-count {
  font-family: v.$font-num;
  color: v.$ink-500;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: v.$sp-3;
}

.detail-tabs {
  margin-top: v.$sp-4;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: v.$sp-2;
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
