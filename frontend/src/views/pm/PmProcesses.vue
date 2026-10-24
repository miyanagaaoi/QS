<script setup>
/**
 * PmProcesses — 项目管理 · 施工实施步骤明细（CH-002）
 * 全局参考表（15 条工序），数据来源 doc/工程项目全周期工期计划表「施工实施步骤明细」。
 */
import { onMounted, ref } from 'vue'

import { listPmProcesses, updatePmProcess } from '@/api/pm'
import PmRefTable from './PmRefTable.vue'

const rows = ref([])
const loading = ref(true)

const columns = [
  { prop: 'seq', label: '序号', width: 64 },
  { prop: 'group_name', label: '工序分组', width: 110, required: true },
  { prop: 'name', label: '工序名称', minWidth: 150, required: true },
  { prop: 'content', label: '主要工作内容', minWidth: 260, textarea: true },
  { prop: 'qc_point', label: '质量控制点 / 关键验收', minWidth: 220, textarea: true },
  { prop: 'predecessor', label: '紧前工序', width: 130 },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listPmProcesses()
  } catch {
    /* 已提示 */
  } finally {
    loading.value = false
  }
}

async function save(row) {
  const updated = await updatePmProcess(row.id, {
    seq: Number(row.seq) || null,
    group_name: row.group_name,
    name: row.name,
    content: row.content,
    qc_point: row.qc_point,
    predecessor: row.predecessor,
  })
  const index = rows.value.findIndex((x) => x.id === row.id)
  if (index >= 0) rows.value[index] = updated
}

onMounted(load)
</script>

<template>
  <PmRefTable
    title="施工实施步骤明细"
    hint="15 条标准工序（土建 / 设备安装 / 电仪自控 / 防腐保温 / 试验检验），可逐条维护"
    :columns="columns"
    :rows="rows"
    :loading="loading"
    :on-save="save"
  />
</template>
