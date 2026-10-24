<script setup>
/**
 * PmScopeBar — 参考表子页的「作用域切换条」（CH-005）
 * ---------------------------------------------------------------------------
 * 三张参考表都分两套数据，本组件统一它们的切换交互：
 *  - **项目模式**：看某个项目的副本（管理员 + 采购员都能改）
 *  - **模板模式**：改全公司标准模板（仅管理员可见；改完只影响"以后新建的项目"）
 *
 * 项目选择写入 URL 的 `?project_id=`（父页面负责），刷新/分享后可定位到同一项目。
 */
import { computed } from 'vue'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  projectId: { type: [Number, null], default: null },
  mode: { type: String, default: 'project' }, // project | template
  isAdmin: { type: Boolean, default: false },
  /** 是否有副本可以"从模板重置" */
  canReset: { type: Boolean, default: false },
})

const emit = defineEmits(['update:projectId', 'update:mode', 'reset'])

const currentName = computed(
  () => props.projects.find((p) => p.id === props.projectId)?.name || '',
)

function onProject(value) {
  emit('update:projectId', value)
  emit('update:mode', 'project')
}
</script>

<template>
  <section class="scope-bar">
    <div class="scope-bar__left">
      <span class="scope-bar__label">当前范围</span>
      <el-radio-group
        v-if="isAdmin"
        :model-value="mode"
        size="small"
        @update:model-value="(v) => emit('update:mode', v)"
      >
        <el-radio-button value="project">项目</el-radio-button>
        <el-radio-button value="template">标准模板</el-radio-button>
      </el-radio-group>
      <span v-else class="scope-bar__tag">项目</span>

      <el-select
        v-if="mode === 'project'"
        :model-value="projectId"
        placeholder="选择项目"
        size="small"
        style="width: 240px"
        @update:model-value="onProject"
      >
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>

      <span v-if="mode === 'template'" class="scope-bar__hint">
        正在维护「标准模板」—— 只影响此后新建的项目，已建项目不受影响
      </span>
      <span v-else-if="currentName" class="scope-bar__hint">仅影响「{{ currentName }}」</span>
    </div>

    <el-button
      v-if="mode === 'project' && projectId && canReset"
      size="small"
      @click="emit('reset')"
    >
      按模板重置本项目的三项参考表
    </el-button>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.scope-bar {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: v.$sp-3 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.scope-bar__left {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
  min-width: 0;
}

.scope-bar__label {
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.scope-bar__tag {
  padding: 2px 8px;
  border-radius: 999px;
  background: v.$brand-50;
  color: v.$brand-800;
  font-size: v.$fs-xs;
}

.scope-bar__hint {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

@include bp.mobile {
  .scope-bar {
    flex-direction: column;
    align-items: stretch;
    gap: v.$sp-2;
  }

  .scope-bar__left {
    :deep(.el-select) {
      width: 100% !important;
    }
  }
}
</style>
