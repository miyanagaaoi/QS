<script setup>
/**
 * SupplierToast — 顶部轻提示条（FR-RWD-21 / 设计稿 C、D、E 屏）
 * ---------------------------------------------------------------------------
 * 固定在顶栏下方（设计稿 top:56px），保存/提交成功与失败都在这里反馈，
 * **不依赖滚动到页面顶部**。失败态可带一个「重试」动作。
 * 这里手写而不复用 ElMessage：设计稿要求通栏深底 + 语义图标 + 内嵌动作按钮，
 * 且要固定在 appbar 之下的绝对位置。
 */
import { onBeforeUnmount, watch } from 'vue'

defineOptions({ name: 'SupplierToast' })

const props = defineProps({
  visible: { type: Boolean, default: false },
  /** success | error | warn | info */
  type: { type: String, default: 'success' },
  message: { type: String, default: '' },
  /** 动作按钮文案；空则不渲染 */
  actionText: { type: String, default: '' },
  /** 自动消失毫秒数；0 表示不自动消失（错误态用） */
  duration: { type: Number, default: 2600 },
})

const emit = defineEmits(['action', 'close'])

let timer = null

function clear() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

watch(
  () => [props.visible, props.message, props.type, props.duration],
  () => {
    clear()
    if (!props.visible || !props.duration) return
    timer = setTimeout(() => emit('close'), props.duration)
  },
  { immediate: true },
)

onBeforeUnmount(clear)

const ICONS = { success: '✓', error: '!', warn: '!', info: 'i' }
</script>

<template>
  <Transition name="st-fade">
    <div v-if="visible && message" class="st" :class="`is-${type}`" role="status" aria-live="polite">
      <span class="st__icon" aria-hidden="true">{{ ICONS[type] || 'i' }}</span>
      <span class="st__text">{{ message }}</span>
      <button
        v-if="actionText"
        type="button"
        class="st__action"
        @click="emit('action')"
      >
        {{ actionText }}
      </button>
      <button type="button" class="st__close" aria-label="关闭提示" @click="emit('close')">×</button>
    </div>
  </Transition>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.st {
  position: fixed;
  top: calc(env(safe-area-inset-top, 0px) + 54px);
  right: v.$sp-3;
  left: v.$sp-3;
  z-index: v.$z-toast;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  padding: 10px v.$sp-3;
  font-size: v.$fs-xs;
  line-height: 1.45;
  color: #fff;
  background: v.$ink-900;
  border-radius: v.$r-md;
  box-shadow: v.$sh-2;
}

.st.is-error {
  background: #7a1c14;
}

.st.is-warn {
  background: #7a4208;
}

.st.is-info {
  background: v.$brand-900;
}

.st__icon {
  flex: none;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 800;
  color: v.$ink-900;
  background: #4ade9b;
  border-radius: 50%;
}

.st.is-error .st__icon,
.st.is-warn .st__icon {
  color: #fff;
  background: rgba(255, 255, 255, 0.28);
}

.st.is-info .st__icon {
  color: v.$brand-900;
  background: #9fe6db;
}

.st__text {
  flex: 1;
  min-width: 0;
}

.st__action {
  flex: none;
  min-height: 30px;
  padding: 0 10px;
  font-size: v.$fs-xs;
  font-weight: 700;
  color: #fff;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: v.$r-md;
  cursor: pointer;
}

.st__close {
  flex: none;
  width: 26px;
  height: 26px;
  font-size: 15px;
  line-height: 1;
  color: rgba(255, 255, 255, 0.72);
  background: transparent;
  border: none;
  cursor: pointer;
}

.st-fade-enter-active,
.st-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.st-fade-enter-from,
.st-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
