<script setup>
/**
 * PmDocuments — 项目管理 · 预算决算配套单据（CH-005）
 * 项目副本可增改删；管理员可切到「标准模板」维护全公司基线。
 */
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createPmDocument,
  deletePmDocument,
  listPmDocuments,
  resetProjectCopies,
  updatePmDocument,
} from '@/api/pm'
import { usePmScope } from '@/composables/usePmScope'
import PmRefTable from './PmRefTable.vue'
import PmScopeBar from './PmScopeBar.vue'

const {
  isAdmin, projects, loadingProjects, mode, projectId, scopeKey, isTemplate,
  currentProject, setMode, setProjectId, loadProjects,
} = usePmScope()

const rows = ref([])
const loading = ref(false)

const columns = [
  { prop: 'seq', label: '序号', width: 64 },
  { prop: 'cost_point', label: '对应管理点', width: 160 },
  { prop: 'name', label: '单据名称', width: 180, required: true },
  { prop: 'usage', label: '用途 / 使用时机', minWidth: 180, textarea: true },
  { prop: 'required_fields', label: '核心栏目（必填字段）', minWidth: 260, textarea: true },
  { prop: 'flow', label: '审批流转节点', minWidth: 220, textarea: true },
  { prop: 'archive', label: '归档要求', minWidth: 180, textarea: true },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listPmDocuments(scopeKey.value)
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(scopeKey, load)

async function save(row) {
  const updated = await updatePmDocument(row.id, {
    seq: Number(row.seq) || null,
    cost_point: row.cost_point,
    name: row.name,
    usage: row.usage,
    required_fields: row.required_fields,
    flow: row.flow,
    archive: row.archive,
  })
  const index = rows.value.findIndex((x) => x.id === row.id)
  if (index >= 0) rows.value[index] = updated
}

async function create(form) {
  await createPmDocument(
    {
      cost_point: form.cost_point || null,
      name: form.name,
      usage: form.usage || null,
      required_fields: form.required_fields || null,
      flow: form.flow || null,
      archive: form.archive || null,
    },
    scopeKey.value,
  )
  await load()
}

async function remove(row) {
  await deletePmDocument(row.id)
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
        <h2 class="page-head__title">预算决算配套单据</h2>
        <p class="page-head__sub">
          {{ isTemplate ? '标准模板（全公司一套，新建项目时按它复制）' : '项目专属单据清单（可增改删）' }}
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
      title="预算决算配套单据"
      hint="12 类单据的必填栏目、审批流转与归档要求（模板维护）"
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
