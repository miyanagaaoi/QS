<script setup>
/**
 * PmRefTable — 参考表通用表格（预算决算管理点 / 配套单据）
 * ---------------------------------------------------------------------------
 * CH-005 起这两张表分"标准模板"与"项目副本"，差异只在列定义与接口，
 * 因此仍抽成一个组件：表格 + 单行编辑弹窗 + 新增 + 删除。
 *
 * 父页面负责：作用域（模板/项目）切换、加载数据、调用保存/新增/删除接口。
 */
import { computed, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: '' },
  /** [{ prop, label, width?, minWidth?, textarea?, required? }] */
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  /** (row) => Promise<void> */
  onSave: { type: Function, required: true },
  /** (form) => Promise<void>，不传则不显示「新增」 */
  onCreate: { type: Function, default: null },
  /** (row) => Promise<void>，不传则不显示「删除」 */
  onDelete: { type: Function, default: null },
})

const dialog = reactive({ visible: false, saving: false, mode: 'edit', form: {}, id: null })
const total = computed(() => props.rows.length)

function emptyForm() {
  const form = {}
  props.columns.forEach((col) => {
    form[col.prop] = ''
  })
  return form
}

function openCreate() {
  dialog.mode = 'create'
  dialog.id = null
  dialog.form = emptyForm()
  dialog.visible = true
}

function openEdit(row) {
  dialog.mode = 'edit'
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
    if (dialog.mode === 'create') {
      await props.onCreate({ ...dialog.form })
      ElMessage.success('已新增')
    } else {
      await props.onSave({ ...dialog.form })
      ElMessage.success('已保存')
    }
    dialog.visible = false
  } catch {
    // request.js 已统一提示后端原文
  } finally {
    dialog.saving = false
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.name || row.point}」？只删当前范围内这一条，不影响标准模板与其它项目。`,
      '删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await props.onDelete(row)
    ElMessage.success('已删除')
  } catch {
    /* 取消或后端拒绝 */
  }
}
</script>

<template>
  <section v-loading="loading" class="pm-ref-card">
    <header class="pm-ref-card__head">
      <div>
        <h3 class="pm-ref-card__title">{{ title }}</h3>
        <p class="pm-ref-card__hint">{{ hint }}</p>
      </div>
      <div class="pm-ref-card__actions">
        <span class="pm-ref-card__count">共 {{ total }} 条</span>
        <el-button v-if="onCreate" size="small" type="primary" @click="openCreate">
          + 新增
        </el-button>
      </div>
    </header>

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
      <el-table-column label="操作" :width="onDelete ? 110 : 80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="onDelete" link type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <div class="pm-ref-card__empty">暂无数据</div>
      </template>
    </el-table>

    <el-dialog
      v-model="dialog.visible"
      :title="`${dialog.mode === 'create' ? '新增' : '编辑'}：${title}`"
      width="640px"
      :close-on-click-modal="false"
    >
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
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-ref-card {
  padding: v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.pm-ref-card__head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
  margin-bottom: v.$sp-3;
}

.pm-ref-card__title {
  margin: 0;
  font-size: v.$fs-lg;
}

.pm-ref-card__hint {
  margin: 3px 0 0;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.pm-ref-card__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
}

.pm-ref-card__count {
  font-size: v.$fs-sm;
  color: v.$ink-400;
  font-family: v.$font-num;
}

.pm-ref-card__empty {
  padding: v.$sp-3 0;
  color: v.$ink-400;
  font-size: v.$fs-sm;
}

.num {
  font-family: v.$font-num;
}

@include bp.mobile {
  .pm-ref-card {
    padding: v.$sp-2;
    overflow-x: auto;
  }
}
</style>
