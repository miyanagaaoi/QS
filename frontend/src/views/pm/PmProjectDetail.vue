<script setup>
/**
 * PmProjectDetail — 项目管理 · 工期计划表（CH-002）
 * ---------------------------------------------------------------------------
 * 一个项目一张表：默认 8 阶段（决策立项 → 缺陷保修），由后端按标准模板生成，
 * 这里支持逐行改工期/交付物/责任人，也可加行、删行、上移下移、一键重置模板。
 *
 * 口径（与 doc/工程项目全周期工期计划表 一致）：
 *  - 单位月；开始月/结束月为"自立项决策起算的累计月数"，由工期自动累加；
 *  - 建设工期合计 = 序号 1~7（不含缺陷保修/质保期）；项目经理在场期 = 序号 4~7。
 *
 * 接口：GET/PUT /api/pm/projects/{id}、PUT .../stages、POST .../stages/reset
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
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

const totalMonths = computed(() =>
  stages.value.reduce((sum, row) => sum + (Number(row.months) || 0), 0),
)
/** 建设工期合计：序号 1~7（不含质保） */
const buildMonths = computed(() =>
  stages.value
    .filter((row) => Number(row.seq) <= 7)
    .reduce((sum, row) => sum + (Number(row.months) || 0), 0),
)
/** 项目经理在场期：序号 4~7（施工准备 → 竣工验收） */
const pmMonths = computed(() =>
  stages.value
    .filter((row) => Number(row.seq) >= 4 && Number(row.seq) <= 7)
    .reduce((sum, row) => sum + (Number(row.months) || 0), 0),
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

/** 重新累加"开始月/结束月"（改工期后调用，保证累计口径一致） */
function recalcMonths() {
  let cursor = 0
  stages.value.forEach((row) => {
    const months = Number(row.months) || 0
    row.start_month = String(cursor)
    row.end_month = String(cursor + months)
    cursor += months
  })
}

function addRow() {
  const nextSeq = stages.value.length ? Math.max(...stages.value.map((r) => Number(r.seq) || 0)) + 1 : 1
  stages.value.push({
    id: null,
    seq: nextSeq,
    name: '',
    group_name: '',
    months: '',
    start_month: '',
    end_month: '',
    deliverables: '',
    pm_role: '',
    owner: '',
  })
  recalcMonths()
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
    recalcMonths()
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
  recalcMonths()
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
      total_months: project.value.total_months,
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
    recalcMonths()
    const payload = stages.value.map((row) => ({
      seq: Number(row.seq),
      name: String(row.name).trim(),
      group_name: row.group_name || null,
      months: row.months === '' ? null : String(row.months),
      start_month: row.start_month === '' ? null : String(row.start_month),
      end_month: row.end_month === '' ? null : String(row.end_month),
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
          工期计划表 · 建设工期 {{ fmt(buildMonths) }} 月 ·
          项目经理在场 {{ fmt(pmMonths) }} 月 · 含质保合计 {{ fmt(totalMonths) }} 月
        </p>
      </div>
      <div class="page-head__actions">
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
        <span class="card__hint">单位：月；开始/结束月为自决策立项起算的累计月数（改工期后自动重算）</span>
      </div>

      <el-table :data="stages" border size="small" style="width: 100%">
        <el-table-column prop="seq" label="序号" width="56" align="center" />
        <el-table-column label="阶段名称" min-width="110">
          <template #default="{ row }"><el-input v-model="row.name" size="small" maxlength="30" /></template>
        </el-table-column>
        <el-table-column label="阶段组" width="110">
          <template #default="{ row }"><el-input v-model="row.group_name" size="small" maxlength="20" /></template>
        </el-table-column>
        <el-table-column label="工期(月)" width="88">
          <template #default="{ row }">
            <el-input v-model="row.months" size="small" @change="recalcMonths" />
          </template>
        </el-table-column>
        <el-table-column label="开始月" width="80">
          <template #default="{ row }"><span class="num">{{ row.start_month ?? '—' }}</span></template>
        </el-table-column>
        <el-table-column label="结束月" width="80">
          <template #default="{ row }"><span class="num">{{ row.end_month ?? '—' }}</span></template>
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
          建设工期（1~7）<b>{{ fmt(buildMonths) }}</b> 月 ·
          项目经理在场（4~7）<b>{{ fmt(pmMonths) }}</b> 月 ·
          全部合计（含质保）<b>{{ fmt(totalMonths) }}</b> 月
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
