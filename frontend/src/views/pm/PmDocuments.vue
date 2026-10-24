<script setup>
/**
 * PmDocuments — 项目管理 · 预算决算配套单据（CH-002）
 * 全局参考表（12 类），数据来源「预算决算配套单据」工作表。
 */
import { onMounted, ref } from 'vue'

import { listPmDocuments, updatePmDocument } from '@/api/pm'
import PmRefTable from './PmRefTable.vue'

const rows = ref([])
const loading = ref(true)

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
    rows.value = await listPmDocuments()
  } catch {
    /* 已提示 */
  } finally {
    loading.value = false
  }
}

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

onMounted(load)
</script>

<template>
  <PmRefTable
    title="预算决算配套单据"
    hint="12 类单据的必填栏目、审批流转与归档要求（模板维护）"
    :columns="columns"
    :rows="rows"
    :loading="loading"
    :on-save="save"
  />
</template>
