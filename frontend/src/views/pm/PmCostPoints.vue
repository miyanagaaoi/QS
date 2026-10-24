<script setup>
/**
 * PmCostPoints — 项目管理 · 预算决算管理点（CH-005）
 * 项目副本可增改删；管理员可切到「标准模板」维护全公司基线。
 */
import { onMounted, ref, watch } from 'vue'

import {
  createPmCostPoint,
  deletePmCostPoint,
  listPmCostPoints,
  resetProjectCopies,
  updatePmCostPoint,
} from '@/api/pm'
import { usePmScope } from '@/composables/usePmScope'
import PmRefTable from './PmRefTable.vue'
import PmScopeBar from './PmScopeBar.vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const {
  isAdmin, projects, loadingProjects, mode, projectId, scopeKey, isTemplate,
  currentProject, setMode, setProjectId, loadProjects,
} = usePmScope()

const rows = ref([])
const loading = ref(false)

const columns = [
  { prop: 'seq', label: '序号', width: 64 },
  { prop: 'phase', label: '环节', width: 110, required: true },
  { prop: 'point', label: '管理点', width: 150, required: true },
  { prop: 'action', label: '关键控制动作', minWidth: 280, textarea: true },
  { prop: 'risk', label: '常见风险 / 红线', minWidth: 220, textarea: true },
  { prop: 'owner', label: '责任主体', width: 130 },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listPmCostPoints(scopeKey.value)
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(scopeKey, load)

async function save(row) {
  const updated = await updatePmCostPoint(row.id, {
    seq: Number(row.seq) || null,
    phase: row.phase,
    point: row.point,
    action: row.action,
    risk: row.risk,
    owner: row.owner,
  })
  const index = rows.value.findIndex((x) => x.id === row.id)
  if (index >= 0) rows.value[index] = updated
}

async function create(form) {
  await createPmCostPoint(
    {
      phase: form.phase,
      point: form.point,
      action: form.action || null,
      risk: form.risk || null,
      owner: form.owner || null,
    },
    scopeKey.value,
  )
  await load()
}

async function remove(row) {
  await deletePmCostPoint(row.id)
  await load()
}

async function resetCopies() {
  if (!projectId.value) return
  try {
    await ElMessageBox.confirm(
      `按标准模板重置「${currentProject.value?.name || ''}」的工序/管理点/单据三项？该项目的自定义修改会丢失。`,
      '按模板重置',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
    await resetProjectCopies(projectId.value)
    ElMessage.success('已按模板重置')
    await load()
  } catch {
    /* 取消 */
  }
}

onMounted(async () => {
  await loadProjects()
  await load()
})
</script>

<template>
  <div class="pm-subpage">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">预算决算管理点</h2>
        <p class="page-head__sub">
          {{ isTemplate ? '标准模板（全公司一套，新建项目时按它复制）' : '项目专属管理点（可增改删）' }}
        </p>
      </div>
    </header>

    <PmScopeBar
      :projects="projects"
      :project-id="projectId"
      :mode="mode"
      :is-admin="isAdmin"
      :can-reset="!isTemplate"
      @update:project-id="setProjectId"
      @update:mode="setMode"
      @reset="resetCopies"
    />

    <PmRefTable
      title="预算决算管理点"
      hint="预算编制 / 过程管控 / 竣工结算 / 财务决算 / 审计配合 五类控制点"
      :columns="columns"
      :rows="rows"
      :loading="loading || loadingProjects"
      :on-save="save"
      :on-create="create"
      :on-delete="remove"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
.pm-subpage { display: flex; flex-direction: column; gap: v.$sp-4; }
.page-head__title { margin: 0; font-size: v.$fs-title; }
.page-head__sub { margin: 3px 0 0; font-size: v.$fs-sm; color: v.$ink-500; }
</style>
