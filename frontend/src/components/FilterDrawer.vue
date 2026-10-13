<script setup>
/**
 * FilterDrawer — 筛选区形态切换（FR-RWD-04）
 * ---------------------------------------------------------------------------
 * ≥768px：筛选条件行内平铺 + 右侧查询/重置按钮（不占用首屏以外的空间）
 * <768px：收成「筛选」按钮 → 底部弹层（el-drawer direction=btt），
 *         避免筛选区把首屏撑满；弹层打开时锁定背景滚动。
 *
 * 用法：
 *   <FilterDrawer :active-count="filterCount" @search="load" @reset="resetFilter">
 *     <el-form-item label="单号"><el-input v-model="query.rfq_no" /></el-form-item>
 *     ...
 *   </FilterDrawer>
 */
import { computed, ref, watch } from 'vue'

import { useBodyScrollLock } from '@/composables/useBodyScrollLock'
import { useBreakpoint } from '@/composables/useBreakpoint'

defineOptions({ name: 'FilterDrawer' })

const props = defineProps({
  /** 弹层标题 */
  title: { type: String, default: '筛选' },
  /** 已生效的筛选条件数量，>0 时在「筛选」按钮上显示角标 */
  activeCount: { type: Number, default: 0 },
  /** 强制行内形态（即使手机端，例如只有一个输入框的简单筛选） */
  inline: { type: Boolean, default: false },
  /** 手机端弹层高度 */
  size: { type: String, default: '72%' },
  /** v-model 控制弹层展开（可选；不传则内部自管） */
  modelValue: { type: Boolean, default: false },
  triggerText: { type: String, default: '筛选' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'search', 'reset'])

const { isMobile } = useBreakpoint()
const visible = ref(props.modelValue)
const showInline = computed(() => props.inline || !isMobile.value)

// 背景滚动锁定（FR-RWD-02）
useBodyScrollLock(visible)

watch(
  () => props.modelValue,
  (value) => {
    if (value !== visible.value) visible.value = value
  },
)

watch(visible, (value) => emit('update:modelValue', value))

function open() {
  visible.value = true
}

function handleSearch() {
  visible.value = false
  emit('search')
}

function handleReset() {
  emit('reset')
}
</script>

<template>
  <!-- 行内形态（平板 / 桌面） -->
  <div v-if="showInline" class="filter-inline">
    <div class="filter-inline__fields">
      <slot />
    </div>
    <div class="filter-inline__actions">
      <slot name="actions">
        <el-button type="primary" :loading="loading" @click="emit('search')">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </slot>
    </div>
  </div>

  <!-- 手机形态：筛选按钮 + 底部弹层 -->
  <div v-else class="filter-mobile">
    <button type="button" class="filter-trigger" @click="open">
      <span class="filter-trigger__label">{{ triggerText }}</span>
      <span v-if="activeCount > 0" class="filter-trigger__count num">{{ activeCount }}</span>
    </button>
    <div class="filter-mobile__extra">
      <slot name="trigger-extra" />
    </div>

    <el-drawer
      v-model="visible"
      direction="btt"
      :size="size"
      :title="title"
      :lock-scroll="false"
      class="filter-drawer"
    >
      <div class="filter-drawer__body">
        <slot />
      </div>
      <template #footer>
        <div class="filter-drawer__footer">
          <el-button class="filter-drawer__btn" @click="handleReset">重置</el-button>
          <el-button class="filter-drawer__btn" type="primary" :loading="loading" @click="handleSearch">
            确定
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

// —— 行内形态 ——
.filter-inline {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: v.$sp-3;
  padding: v.$sp-3 v.$sp-4;
  margin-bottom: v.$sp-3;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
}

.filter-inline__fields {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: v.$sp-2 v.$sp-3;
  flex: 1;
  min-width: 0;

  :deep(.el-form-item) {
    margin: 0;
  }
}

.filter-inline__actions {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex: none;
}

// —— 手机形态 ——
.filter-mobile {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-bottom: v.$sp-2;
}

.filter-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: v.$sp-1;
  min-height: v.$touch-target; // FR-RWD-06
  padding: 0 v.$sp-4;
  font-size: v.$fs-body;
  font-weight: 600;
  color: v.$brand-700;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;
  cursor: pointer;

  &:active {
    background: v.$brand-50;
  }
}

.filter-trigger__count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  font-size: 11px;
  line-height: 18px;
  color: #fff;
  text-align: center;
  background: v.$brand-700;
  border-radius: 100px;
}

.filter-mobile__extra {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
}

.filter-drawer__body {
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;

  :deep(.el-form-item) {
    margin: 0;
  }
}

.filter-drawer__footer {
  display: flex;
  gap: v.$sp-3;
}

.filter-drawer__btn {
  flex: 1;
  min-height: v.$touch-target;
  margin-left: 0 !important;
}

@include bp.tablet-up {
  .filter-drawer__btn {
    flex: none;
  }
}
</style>
