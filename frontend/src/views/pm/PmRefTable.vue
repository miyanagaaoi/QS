<script setup>
/**
 * PmRefTable — 项目管理里的「全局参考表」通用表格（施工工序 / 预算决算管理点 / 配套单据）
 * ---------------------------------------------------------------------------
 * 为什么做成组件：这三张表结构一致（只读列表 + 单行编辑），差异只在列定义，
 * 抽成一个组件避免三份几乎相同的代码（也符合 PRD/AGENTS 的"同一件事只记一处"）。
 *
 * 数据是**全局一套**（不按项目复制），首次启动由 `backend/app/pm_seed.py` 写入默认值，
 * 之后以数据库为准。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: '' },
  /** [{ prop, label, width?, minWidth?, textarea? }] */
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  /** (row) => Promise<void> 保存单行 */
  onSave: { type: Function, required: true },
  loading: { type: Boolean, default: false },
  /** 表格分组列：按该 prop 合并展示分组标签（可选） */
  groupProp: { type: String, default: '' },
})

const dialog = reactive({ visible: false, saving: false, form: {}, id: null })

const total = computed(() => props.rows.length)

function openEdit(row) {
  dialog.id = row.id
  dialog.form = { ...row }
  dialog.visible = true
}

async function submit() {
  const missing = props.columns.find(
    (col) => col.required && !String(dialog.form[col.prop] ?? '').trim(),
  )
  if (missing) {
    ElMessage.warning(`请填写「${missing.label}」`)
    return
  }
  dialog.saving = true
  try {
    await props.onSave({ ...dialog.form })
    ElMessage.success('已保存')
    dialog.visible = false
  } catch {
    /* request.js 已统一提示后端原文 */
  } finally {
    dialog.saving = false
  }
}
</script>

<template>
  <div v-loading="loading" class="pm-ref">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">{{ title }}</h2>
        <p class="page-head__sub">{{ hint }}</p>
      </div>
      <span class="page-head__count">共 {{ total }} 条</span>
    </header>

    <section class="card">
      <el-table :data="rows" border size="small" style="width: 100%" row-key="id">
        <el-table-column
          v-for="col in columns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :width="col.width"
          :min-width="col.minWidth"
          :show-overflow-tooltip="!col.textarea"
        >
          <template #default="{ row }">
            <span v-if="col.prop === 'seq'" class="num">{{ row.seq }}</span>
            <span v-else>{{ row[col.prop] ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog.visible" :title="`编辑：${title}`" width="640px" :close-on-click-modal="false">
      <el-form label-width="120px" label-position="right">
        <el-form-item
          v-for="col in columns"
          :key="col.prop"
          :label="col.label"
          :required="col.required"
        >
          <el-input
            v-model="dialog.form[col.prop]"
            :type="col.textarea ? 'textarea' : 'text'"
            :rows="col.textarea ? 3 : undefined"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-ref {
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

.page-head__count {
  margin-left: auto;
  font-size: v.$fs-sm;
  color: v.$ink-400;
  font-family: v.$font-num;
}

.card {
  padding: v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.num {
  font-family: v.$font-num;
}

@include bp.mobile {
  .card {
    padding: v.$sp-2;
    overflow-x: auto;
  }
}
</style>
