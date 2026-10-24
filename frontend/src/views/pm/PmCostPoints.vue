<script setup>
/**
 * PmCostPoints — 项目管理 · 预算决算管理点（CH-002）
 * 全局参考表（14 条），数据来源「预算决算管理点」工作表。
 */
import { onMounted, ref } from 'vue'

import { listPmCostPoints, updatePmCostPoint } from '@/api/pm'
import PmRefTable from './PmRefTable.vue'

const rows = ref([])
const loading = ref(true)

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
    rows.value = await listPmCostPoints()
  } catch {
    /* 已提示 */
  } finally {
    loading.value = false
  }
}

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

onMounted(load)
</script>

<template>
  <PmRefTable
    title="预算决算管理点"
    hint="预算编制 / 过程管控 / 竣工结算 / 财务决算 / 审计配合 五类共 14 个控制点"
    :columns="columns"
    :rows="rows"
    :loading="loading"
    :on-save="save"
  />
</template>
