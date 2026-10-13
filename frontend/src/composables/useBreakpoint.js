/**
 * 断点组合式函数（PRD 10.1 / FR-RWD-01）
 * ---------------------------------------------------------------------------
 * isMobile  < 768px
 * isTablet  768 ~ 1199px
 * isDesktop >= 1200px
 *
 * 关键约束：
 *  1. **只以视口宽度为准，禁止 UA 嗅探**（平板横竖屏、桌面缩窄窗口都要正确响应）。
 *  2. 断点数值只有一处定义：src/styles/breakpoints.scss。
 *     vite.config.js 在构建期解析该文件并注入 __XJ_BREAKPOINTS__，CSS 与 JS 永远一致。
 *  3. 全局只注册一份 resize/orientationchange 监听（单例），多个组件调用不会重复绑定。
 */
import { computed, ref } from 'vue'

// __XJ_BREAKPOINTS__ 由 vite.config.js 的 define 注入（值来自 styles/breakpoints.scss）
const INJECTED = typeof __XJ_BREAKPOINTS__ !== 'undefined' ? __XJ_BREAKPOINTS__ : null
/** 兜底值：正常情况下由 vite define 注入，不生效 */
const BP = INJECTED && INJECTED.tablet && INJECTED.desktop ? INJECTED : { tablet: 768, desktop: 1200 }

const viewportWidth = ref(typeof window === 'undefined' ? BP.desktop : window.innerWidth)
const landscape = ref(typeof window === 'undefined' ? false : window.innerWidth >= window.innerHeight)

let listening = false
let frame = 0

function sync() {
  frame = 0
  if (typeof window === 'undefined') return
  viewportWidth.value = window.innerWidth
  landscape.value = window.innerWidth >= window.innerHeight
}

function scheduleSync() {
  if (frame) return
  const raf = typeof window !== 'undefined' && window.requestAnimationFrame
  frame = raf ? window.requestAnimationFrame(sync) : window.setTimeout(sync, 16)
}

function startListening() {
  if (listening || typeof window === 'undefined') return
  listening = true
  sync()
  window.addEventListener('resize', scheduleSync, { passive: true })
  window.addEventListener('orientationchange', scheduleSync, { passive: true })
  const mql = window.matchMedia?.('(orientation: landscape)')
  // 旧版 Safari 只有 addListener
  if (mql?.addEventListener) mql.addEventListener('change', scheduleSync)
  else if (mql?.addListener) mql.addListener(scheduleSync)
}

const isTabletUp = computed(() => viewportWidth.value >= BP.tablet)
const isDesktop = computed(() => viewportWidth.value >= BP.desktop)
const isTablet = computed(() => viewportWidth.value >= BP.tablet && viewportWidth.value < BP.desktop)
const isMobile = computed(() => viewportWidth.value < BP.tablet)
const breakpoint = computed(() => (isDesktop.value ? 'desktop' : isTablet.value ? 'tablet' : 'mobile'))

/**
 * @returns {{
 *   width: import('vue').Ref<number>,
 *   isMobile: import('vue').ComputedRef<boolean>,
 *   isTablet: import('vue').ComputedRef<boolean>,
 *   isDesktop: import('vue').ComputedRef<boolean>,
 *   isTabletUp: import('vue').ComputedRef<boolean>,
 *   isLandscape: import('vue').Ref<boolean>,
 *   breakpoint: import('vue').ComputedRef<'mobile'|'tablet'|'desktop'>,
 *   breakpoints: { tablet: number, desktop: number },
 *   matches: (min: number) => boolean,
 * }}
 */
export function useBreakpoint() {
  startListening()
  return {
    width: viewportWidth,
    isMobile,
    isTablet,
    isDesktop,
    isTabletUp,
    isLandscape: landscape,
    breakpoint,
    breakpoints: BP,
    /** 非响应式即时判断，适合在回调/计算外临时用 */
    matches: (min) => viewportWidth.value >= min,
  }
}

/** 表格 ↔ 卡片等「同一数据换形态」的便捷判断 */
export function useIsMobile() {
  startListening()
  return isMobile
}

export default useBreakpoint
