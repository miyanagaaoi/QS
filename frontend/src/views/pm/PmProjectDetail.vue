<script setup>
/**
 * PmProjectDetail — 项目管理 · 工期计划表（CH-002）
 * ---------------------------------------------------------------------------
 * 一个项目一张表：默认 8 阶段（决策立项 → 缺陷保修），由后端按标准模板生成，
 * 这里支持逐行改工期/交付物/责任人，也可加行、删行、上移下移、一键重置模板。
 *
 * 口径（与 doc/工程项目全周期工期计划表 一致）：
 *  - CH-013 起单位统一为**天**：每行直接选计划开始/结束日期，工期 = 日期差（自动算）；
 *  - 建设工期合计 = 序号 1~7（不含缺陷保修/质保期）；项目经理在场期 = 序号 4~7。
 *
 * 接口：GET/PUT /api/pm/projects/{id}、PUT .../stages、POST .../stages/reset
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  exportProjectStages,
  getProject,
  resetProjectStages,
  saveProjectStages,
  updateProject,
} from '@/api/pm'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const projectId = Number(route.params.id)
const loading = ref(true)
const saving = ref(false)
const exporting = ref(false)
const project = ref(null)
const stages = ref([])

const STAGES = [
  '决策立项', '勘察设计', '招标签约', '施工准备',
  '施工实施', '调试验收', '竣工验收', '缺陷保修',
]
const STATUS_OPTIONS = [
  { value: 'planning', label: '未开工' },
  { value: 'active', label: '进行中' },
  { value: 'done', label: '已竣工' },
  { value: 'paused', label: '暂停' },
]

/** 基本信息（可改的部分） */
const info = reactive({
  current_stage: '',
  status: 'active',
  start_date: '',
  plan_end_date: '',
  manager: '',
})

/** 单行工期（天）：有起止日期就用日期差，否则用 days 字段 */
function rowDays(row) {
  if (row.plan_start_date && row.plan_end_date) {
    const start = new Date(`${row.plan_start_date}T00:00:00Z`)
    const end = new Date(`${row.plan_end_date}T00:00:00Z`)
    const diff = Math.round((end - start) / 86400000)
    return diff > 0 ? diff : 0
  }
  return Number(row.days) || 0
}

const totalDays = computed(() => stages.value.reduce((sum, row) => sum + rowDays(row), 0))
/** 建设工期合计：序号 1~7（不含质保） */
const buildDays = computed(() =>
  stages.value
    .filter((row) => Number(row.seq) <= 7)
    .reduce((sum, row) => sum + rowDays(row), 0),
)
/** 项目经理在场期：序号 4~7（施工准备 → 竣工验收） */
const pmDays = computed(() =>
  stages.value
    .filter((row) => Number(row.seq) >= 4 && Number(row.seq) <= 7)
    .reduce((sum, row) => sum + rowDays(row), 0),
)

function fmt(n) {
  const v = Number(n) || 0
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

async function load() {
  loading.value = true
  try {
    const data = await getProject(projectId)
    project.value = data
    stages.value = (data.stages || []).map((row) => ({ ...row }))
    info.current_stage = data.current_stage || ''
    info.status = data.status || 'active'
    info.start_date = data.start_date || ''
    info.plan_end_date = data.plan_end_date || ''
    info.manager = data.manager || ''
  } catch {
    // request.js 统一提示
  } finally {
    loading.value = false
  }
}

/** 把日期串（YYYY-MM-DD）加 n 天 */
function addDays(dateText, n) {
  if (!dateText) return ''
  const base = new Date(`${dateText}T00:00:00Z`)
  base.setUTCDate(base.getUTCDate() + Number(n || 0))
  return base.toISOString().slice(0, 10)
}

/** 改「工期(天)」：以本行开始日为准，重算本行结束日，并顺延后续各阶段（保持首尾相接） */
function recalcFromDays(index) {
  const rows = stages.value
  let cursor = rows[index]?.plan_start_date || ''
  for (let i = index; i < rows.length; i += 1) {
    const row = rows[i]
    if (cursor) {
      row.plan_start_date = cursor
      row.plan_end_date = addDays(cursor, rowDays(row))
      cursor = row.plan_end_date
    } else {
      row.plan_end_date = ''
    }
    row.days = rowDays(row)
  }
  recalcTotals()
}

/** 改「计划开始」：重算本行结束日并顺延后续 */
function recalcFromStart(index) {
  recalcFromDays(index)
}

/** 改「计划结束」：只重算本行工期 */
function recalcFromEnd(index) {
  const row = stages.value[index]
  row.days = rowDays(row)
  recalcTotals()
}

/** 把各行天数写回 days 字段（保存前调用） */
function recalcTotals() {
  stages.value.forEach((row) => {
    row.days = rowDays(row)
  })
}

function addRow() {
  const nextSeq = stages.value.length ? Math.max(...stages.value.map((r) => Number(r.seq) || 0)) + 1 : 1
  stages.value.push({
    id: null,
    seq: nextSeq,
    name: '',
    group_name: '',
    days: '',
    plan_start_date: '',
    plan_end_date: '',
    deliverables: '',
    pm_role: '',
    owner: '',
  })
  recalcTotals()
}

async function removeRow(index) {
  try {
    await ElMessageBox.confirm(`确认删除第 ${stages.value[index].seq} 行？`, '删除阶段', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    stages.value.splice(index, 1)
    stages.value.forEach((row, i) => { row.seq = i + 1 })
    recalcTotals()
  } catch {
    /* 取消 */
  }
}

function move(index, delta) {
  const target = index + delta
  if (target < 0 || target >= stages.value.length) return
  const list = stages.value
  ;[list[index], list[target]] = [list[target], list[index]]
  list.forEach((row, i) => { row.seq = i + 1 })
  recalcTotals()
}

async function saveInfo() {
  if (info.start_date && info.plan_end_date && info.plan_end_date < info.start_date) {
    ElMessage.warning('计划竣工日期不能早于开工日期')
    return
  }
  saving.value = true
  try {
    await updateProject(projectId, {
      name: project.value.name,
      code: project.value.code,
      current_stage: info.current_stage || null,
      start_date: info.start_date || null,
      plan_end_date: info.plan_end_date || null,
      total_days: totalDays.value || null,
      manager: info.manager || null,
      status: info.status,
      remark: project.value.remark,
    })
    ElMessage.success('项目信息已保存')
    await load()
  } catch {
    /* 已提示 */
  } finally {
    saving.value = false
  }
}

async function saveStages() {
  if (!stages.value.length) {
    ElMessage.warning('阶段表不能为空')
    return
  }
  const bad = stages.value.find((row) => !String(row.name || '').trim())
  if (bad) {
    ElMessage.warning(`第 ${bad.seq} 行缺少阶段名称`)
    return
  }
  saving.value = true
  try {
    recalcTotals()
    const payload = stages.value.map((row) => ({
      seq: Number(row.seq),
      name: String(row.name).trim(),
      group_name: row.group_name || null,
      days: rowDays(row),
      plan_start_date: row.plan_start_date || null,
      plan_end_date: row.plan_end_date || null,
      deliverables: row.deliverables || null,
      pm_role: row.pm_role || null,
      owner: row.owner || null,
    }))
    await saveProjectStages(projectId, payload)
    ElMessage.success('工期计划表已保存')
    await load()
  } catch {
    /* 已提示 */
  } finally {
    saving.value = false
  }
}

async function resetStages() {
  try {
    await ElMessageBox.confirm(
      '按标准 8 阶段模板重置？当前修改会丢失。',
      '重置工期计划表',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
    await resetProjectStages(projectId)
    ElMessage.success('已按标准模板重置')
    await load()
  } catch {
    /* 取消 */
  }
}

/** 导出本项目工期计划表（xlsx） */
async function exportStages() {
  if (!project.value) return
  exporting.value = true
  try {
    await exportProjectStages(project.value.id, project.value.name)
  } catch {
    // request.js 已提示
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="pm-detail">
    <header class="page-head">
      <div>
        <button class="back" type="button" @click="router.push('/pm')">← 返回项目管理</button>
        <h2 class="page-head__title">
          {{ project?.name || '项目' }}
          <span v-if="project?.code" class="code">{{ project.code }}</span>
        </h2>
        <p class="page-head__sub">
          工期计划表 · 建设工期 {{ fmt(buildDays) }} 天 ·
          项目经理在场 {{ fmt(pmDays) }} 天 · 含质保合计 {{ fmt(totalDays) }} 天
        </p>
      </div>
      <div class="page-head__actions">
        <el-button :loading="exporting" @click="exportStages">导出 Excel</el-button>
        <el-button :loading="saving" @click="resetStages">重置为标准模板</el-button>
        <el-button type="primary" :loading="saving" @click="saveStages">保存阶段表</el-button>
      </div>
    </header>

    <!-- 项目基本信息 -->
    <section class="card">
      <div class="card__head">
        <h3 class="card__title">项目信息</h3>
        <span class="card__hint">当前阶段手工维护；进度按开工日至计划竣工日自动计算</span>
      </div>
      <div class="info-grid">
        <label class="field">
          <span class="field__label">当前阶段</span>
          <el-select v-model="info.current_stage" clearable placeholder="未设置">
            <el-option v-for="s in STAGES" :key="s" :label="s" :value="s" />
          </el-select>
        </label>
        <label class="field">
          <span class="field__label">状态</span>
          <el-select v-model="info.status">
            <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </label>
        <label class="field">
          <span class="field__label">开工日期</span>
          <el-date-picker v-model="info.start_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
        </label>
        <label class="field">
          <span class="field__label">计划竣工</span>
          <el-date-picker v-model="info.plan_end_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
        </label>
        <label class="field">
          <span class="field__label">项目经理</span>
          <el-input v-model="info.manager" maxlength="50" />
        </label>
        <div class="field field--action">
          <el-button type="primary" :loading="saving" @click="saveInfo">保存信息</el-button>
        </div>
      </div>
      <p class="progress-line">
        总体进度 <b>{{ project?.progress ?? 0 }}%</b>
        <span v-if="project?.remaining_days !== null && project?.remaining_days !== undefined">
          · {{ project.remaining_days < 0 ? `已超期 ${Math.abs(project.remaining_days)} 天` : `剩余 ${project.remaining_days} 天` }}
        </span>
      </p>
    </section>

    <!-- 阶段表 -->
    <section class="card">
      <div class="card__head">
        <h3 class="card__title">工期计划表</h3>
        <span class="card__hint">单位：天；直接选计划开始/结束日期，工期按日期差自动计算，改一天后续阶段自动顺延</span>
      </div>

      <el-table :data="stages" border size="small" style="width: 100%">
        <el-table-column prop="seq" label="序号" width="56" align="center" />
        <el-table-column label="阶段名称" min-width="110">
          <template #default="{ row }"><el-input v-model="row.name" size="small" maxlength="30" /></template>
        </el-table-column>
        <el-table-column label="阶段组" width="110">
          <template #default="{ row }"><el-input v-model="row.group_name" size="small" maxlength="20" /></template>
        </el-table-column>
        <el-table-column label="工期(天)" width="90">
            <template #default="{ row, $index }">
              <el-input
                v-model="row.days"
                size="small"
                placeholder="天"
                @change="() => recalcFromDays($index)"
              />
            </template>
          </el-table-column>
          <el-table-column label="计划开始" width="150">
            <template #default="{ row, $index }">
              <el-date-picker
                v-model="row.plan_start_date"
                type="date"
                size="small"
                value-format="YYYY-MM-DD"
                placeholder="选日期"
                style="width: 100%"
                @change="() => recalcFromStart($index)"
              />
            </template>
          </el-table-column>
          <el-table-column label="计划结束" width="150">
            <template #default="{ row, $index }">
              <el-date-picker
                v-model="row.plan_end_date"
                type="date"
                size="small"
                value-format="YYYY-MM-DD"
                placeholder="选日期"
                style="width: 100%"
                @change="() => recalcFromEnd($index)"
              />
            </template>
          </el-table-column>
        <el-table-column label="关键交付物 / 里程碑" min-width="200">
          <template #default="{ row }"><el-input v-model="row.deliverables" size="small" maxlength="300" /></template>
        </el-table-column>
        <el-table-column label="项目经理角色" min-width="140">
          <template #default="{ row }"><el-input v-model="row.pm_role" size="small" maxlength="60" /></template>
        </el-table-column>
        <el-table-column label="责任主体" width="110">
          <template #default="{ row }"><el-input v-model="row.owner" size="small" maxlength="60" /></template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ $index }">
            <el-button link type="primary" @click="move($index, -1)">上移</el-button>
            <el-button link type="danger" @click="removeRow($index)">删</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">阶段表为空，点下方「+ 添加阶段」或「重置为标准模板」</div>
        </template>
      </el-table>

      <div class="table-foot">
        <el-button @click="addRow">+ 添加阶段</el-button>
        <span class="table-foot__sum">
          建设工期（1~7）<b>{{ fmt(buildDays) }}</b> 天 ·
          项目经理在场（4~7）<b>{{ fmt(pmDays) }}</b> 天 ·
          全部合计（含质保）<b>{{ fmt(totalDays) }}</b> 天
        </span>
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-detail {
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
  margin: 6px 0 0;
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
  gap: v.$sp-2;
}

.back {
  padding: 0;
  border: none;
  background: none;
  color: v.$brand-700;
  font-size: v.$fs-sm;
  cursor: pointer;
}

.code {
  margin-left: 8px;
  font-family: v.$font-num;
  font-size: v.$fs-sm;
  color: v.$ink-400;
  font-weight: 400;
}

.card {
  padding: v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.card__head {
  display: flex;
  align-items: baseline;
  gap: v.$sp-2;
  margin-bottom: v.$sp-3;
}

.card__title {
  margin: 0;
  font-size: v.$fs-lg;
}

.card__hint {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: v.$sp-3;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field__label {
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.field--action {
  justify-content: flex-end;
}

.progress-line {
  margin: v.$sp-3 0 0;
  font-size: v.$fs-sm;
  color: v.$ink-500;

  b {
    font-family: v.$font-num;
    color: v.$brand-800;
  }
}

.table-foot {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  margin-top: v.$sp-3;
}

.table-foot__sum {
  font-size: v.$fs-sm;
  color: v.$ink-500;

  b {
    font-family: v.$font-num;
    color: v.$ink-900;
  }
}

.num {
  font-family: v.$font-num;
}

.empty-text {
  padding: v.$sp-3 0;
  color: v.$ink-400;
  font-size: v.$fs-sm;
}

@include bp.mobile {
  .page-head {
    flex-direction: column;
  }

  .page-head__actions {
    margin-left: 0;
    width: 100%;

    :deep(.el-button) {
      flex: 1;
      min-height: v.$touch-target;
    }
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
