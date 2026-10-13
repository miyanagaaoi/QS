/**
 * 375px 移动端实测脚本（task-6 自检用，非业务代码）
 * 输出：视口宽、页面 scrollWidth、卡片数、越界元素清单、热区 <44px 的可交互元素清单。
 */
(() => {
  const vw = innerWidth
  const vh = innerHeight
  const over = []
  const small = []

  const pages = document.querySelectorAll('.sys-page')
  const root = pages.length ? pages[0] : document.body

  root.querySelectorAll('*').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.right > vw + 1 || r.left < -1) {
      over.push({
        tag: el.tagName.toLowerCase(),
        cls: String(el.className || '').slice(0, 64),
        left: Math.round(r.left),
        right: Math.round(r.right),
        w: Math.round(r.width),
        text: String(el.textContent || '').trim().slice(0, 18),
      })
    }
  })

  const INTERACTIVE = 'button, a, input, textarea, select, [role="button"], .el-button, .el-input__inner, .el-select__wrapper'
  root.querySelectorAll(INTERACTIVE).forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.height < 44 || r.width < 44) {
      small.push({
        cls: String(el.className || '').slice(0, 48),
        w: Math.round(r.width),
        h: Math.round(r.height),
        text: String(el.textContent || el.value || '').trim().slice(0, 14),
      })
    }
  })

  // 只看「真正的按钮/链接」里的最小热区，输入框单独统计（输入框有 label 包裹，热区按 label 算）
  const minBtn = { w: 9999, h: 9999, text: '' }
  root.querySelectorAll('button, .el-button, a, [role="button"]').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.height < minBtn.h || (r.height === minBtn.h && r.width < minBtn.w)) {
      minBtn.w = Math.round(r.width)
      minBtn.h = Math.round(r.height)
      minBtn.text = String(el.textContent || '').trim().slice(0, 16)
    }
  })

  return JSON.stringify({
    vw,
    vh,
    scrollW: document.documentElement.scrollWidth,
    hasHScroll: document.documentElement.scrollWidth > vw,
    cards: document.querySelectorAll('.dt-card').length,
    tables: document.querySelectorAll('.data-table__table').length,
    overCount: over.length,
    over: over.slice(0, 20),
    smallCount: small.length,
    small: small.slice(0, 20),
    minBtn,
  })
})()
