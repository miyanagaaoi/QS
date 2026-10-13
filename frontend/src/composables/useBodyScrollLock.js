/**
 * 背景滚动锁定（PRD 10.4 / FR-RWD-02：抽屉打开时锁定背景滚动）
 * ---------------------------------------------------------------------------
 * 用计数方式支持多个弹层嵌套；锁定期间同时补偿滚动条宽度，避免页面横向跳动。
 * 与 Element Plus 的 lock-scroll 二选一：本项目在自管弹层里显式调用本函数，
 * 并把 el-drawer 的 :lock-scroll 设为 false，避免双重处理。
 */
import { getCurrentInstance, onBeforeUnmount, watch } from 'vue'

let lockCount = 0
let savedOverflow = ''
let savedPaddingRight = ''
let savedTouchAction = ''

function applyLock() {
  if (typeof document === 'undefined') return
  const body = document.body
  if (lockCount === 0) {
    savedOverflow = body.style.overflow
    savedPaddingRight = body.style.paddingRight
    savedTouchAction = body.style.touchAction
    const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth)
    body.style.overflow = 'hidden'
    body.style.touchAction = 'none'
    if (scrollbarWidth > 0) body.style.paddingRight = `${scrollbarWidth}px`
    body.classList.add('xj-scroll-locked')
  }
  lockCount += 1
}

function releaseLock() {
  if (typeof document === 'undefined') return
  lockCount = Math.max(0, lockCount - 1)
  if (lockCount > 0) return
  const body = document.body
  body.style.overflow = savedOverflow
  body.style.paddingRight = savedPaddingRight
  body.style.touchAction = savedTouchAction
  body.classList.remove('xj-scroll-locked')
}

/**
 * @param {boolean | import('vue').Ref<boolean>} source 是否锁定
 * @returns {{ lock: () => void, unlock: () => void }}
 */
export function useBodyScrollLock(source) {
  let active = false

  function setLocked(next) {
    const wanted = Boolean(next)
    if (wanted === active) return
    active = wanted
    if (wanted) applyLock()
    else releaseLock()
  }

  if (source && typeof source === 'object' && 'value' in source) {
    watch(source, setLocked, { immediate: true })
  } else {
    setLocked(source)
  }

  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      if (active) {
        active = false
        releaseLock()
      }
    })
  }

  return {
    lock: () => setLocked(true),
    unlock: () => setLocked(false),
  }
}

export default useBodyScrollLock
