<script setup>
/**
 * StickyBar — 手机端底部固定操作栏（FR-RWD-19 / PRD 10.3-4）
 * ---------------------------------------------------------------------------
 * 手机端：position: fixed 吸底，滚动中始终可达；含 safe-area-inset-bottom
 *         适配 iPhone 底部横条。
 * ≥768px：默认改为文档流内的 sticky（不遮挡表格/报表），可用 mode="fixed" 强制吸底。
 *
 * 用法（报价填报页）：
 *   <StickyBar>
 *     <span>已填 <b class="num">7/10</b> 行</span>
 *     <template #actions>
 *       <el-button @click="save">保存</el-button>
 *       <el-button type="primary" @click="submit">提交报价</el-button>
 *     </template>
 *   </StickyBar>
 */
import { computed } from 'vue'

import { useBreakpoint } from '@/composables/useBreakpoint'

defineOptions({ name: 'StickyBar' })

const props = defineProps({
  /** auto(默认)：手机吸底 / 大屏随流；fixed：始终吸底；inline：始终随流 */
  mode: { type: String, default: 'auto' },
  /** 是否适配安全区 */
  safeArea: { type: Boolean, default: true },
  /** 上边框 + 阴影 */
  bordered: { type: Boolean, default: true },
})

const { isMobile } = useBreakpoint()

const isFixed = computed(() => props.mode === 'fixed' || (props.mode === 'auto' && isMobile.value))
</script>

<template>
  <div
    class="sticky-bar"
    :class="{ 'is-fixed': isFixed, 'is-bordered': bordered, 'is-safe': safeArea }"
    role="group"
  >
    <div class="sticky-bar__inner">
      <div class="sticky-bar__info">
        <slot />
      </div>
      <div v-if="$slots.actions" class="sticky-bar__actions">
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.sticky-bar {
  background: v.$surface;
}

.sticky-bar.is-bordered {
  border-top: 1px solid v.$line;
}

.sticky-bar__inner {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: v.$sp-2 v.$sp-3;
  min-height: v.$bottom-bar-h;
}

.sticky-bar__info {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.sticky-bar__actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: v.$sp-2;

  :deep(.el-button) {
    margin-left: 0;
  }
}

// 吸底形态
.sticky-bar.is-fixed {
  position: fixed;
  right: 0;
  left: 0;
  bottom: 0;
  z-index: v.$z-sticky;
  box-shadow: v.$sh-3;
}

.sticky-bar.is-fixed.is-safe {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

// 随流形态：贴在内容底部
.sticky-bar:not(.is-fixed) {
  position: sticky;
  bottom: 0;
  z-index: v.$z-sticky - 100;
}
</style>
