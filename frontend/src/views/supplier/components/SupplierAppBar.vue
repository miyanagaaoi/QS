<script setup>
/**
 * SupplierAppBar — 供货商侧手机顶栏（设计稿 03-pages-supplier.html 的 .appbar）
 * ---------------------------------------------------------------------------
 * 高 46px、品牌深墨青底、白字；左侧可返回；右侧一枚轻量徽标（剩余时间 / 已截止）。
 * 已截止时整体转为中性灰（设计稿 F 屏 #3A444F），让"锁定"一目了然。
 * 自带 safe-area-inset-top 适配（刘海屏），并与页面 sticky 定位配合。
 */
defineOptions({ name: 'SupplierAppBar' })

defineProps({
  title: { type: String, default: '' },
  /** 显示返回箭头 */
  back: { type: Boolean, default: false },
  /** 右侧徽标文案；空则不渲染 */
  badge: { type: String, default: '' },
  /** 徽标语义色：default | warn | danger | ok */
  badgeTone: { type: String, default: 'default' },
  /** 顶栏色调：brand（进行中）| closed（已截止只读） */
  tone: { type: String, default: 'brand' },
})

const emit = defineEmits(['back'])
</script>

<template>
  <header class="sab" :class="`is-${tone}`">
    <button
      v-if="back"
      type="button"
      class="sab__icon"
      aria-label="返回"
      @click="emit('back')"
    >
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <path d="M10 3L5 8l5 5" />
      </svg>
    </button>
    <h1 class="sab__title">{{ title }}</h1>
    <span class="sab__spacer" />
    <span v-if="badge" class="sab__badge" :class="`is-${badgeTone}`">{{ badge }}</span>
    <slot name="right" />
  </header>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.sab {
  position: sticky;
  top: 0;
  z-index: v.$z-sticky;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex: none;
  min-height: 46px;
  padding: env(safe-area-inset-top, 0px) v.$sp-3 0;
  color: #fff;
  background: v.$brand-800;

  &.is-closed {
    background: #3a444f;
  }
}

.sab__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: v.$touch-target;
  height: v.$touch-target;
  margin-left: calc(-1 * #{v.$sp-2});
  color: #fff;
  background: transparent;
  border: none;
  border-radius: v.$r-md;
  cursor: pointer;

  &:active {
    background: rgba(255, 255, 255, 0.14);
  }
}

.sab__title {
  font-size: v.$fs-body;
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sab__spacer {
  flex: 1;
}

.sab__badge {
  flex: none;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  background: rgba(255, 255, 255, 0.16);
  border-radius: 100px;

  &.is-warn {
    color: #ffd9a8;
    background: rgba(255, 255, 255, 0.18);
  }

  &.is-danger {
    color: #ffd2cb;
    background: rgba(180, 35, 24, 0.45);
  }

  &.is-ok {
    color: #b7f0d3;
    background: rgba(15, 123, 79, 0.42);
  }
}
</style>
