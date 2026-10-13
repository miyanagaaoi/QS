/**
 * 375px 移动端实测（第 3 版）
 * ---------------------------------------------------------------------------
 * 关键发现：AdminLayout 在手机端把「顶部栏」与「主内容区」放成了 flex 行内并排
 * （.admin-layout 没有 flex-direction: column），导致 375px 下主内容区只有 ~180px 宽，
 * 内容被 body{overflow-x:hidden} 裁切（所以页面级 scrollWidth 仍是 375，看不出溢出）。
 *
 * 本脚本提供两种模式的度量：
 *   mode=bug   —— 原样（复现 fe-base 报的越界）
 *   mode=fix   —— 运行时把 .admin-layout 的 flex-direction 改成 column（模拟布局修好后的状态），
 *                 用来证明「我的页面本身」在正确的 375px 布局下是否还有越界/小热区问题。
 */
(() => {
  const mode = (typeof window !== 'undefined' && window.__MEASURE_MODE) || 'fix'

  if (mode === 'fix') {
    const layout = document.querySelector('.admin-layout')
    if (layout) layout.style.flexDirection = 'column'
  }

  const vw = innerWidth
  const root = document.querySelector('.sys-page') || document.body
  const head = (el) => ({
    cls: String(el.className || '').slice(0, 44),
    left: Math.round(el.getBoundingClientRect().left),
    right: Math.round(el.getBoundingClientRect().right),
    w: Math.round(el.getBoundingClientRect().width),
    text: String(el.textContent || '').trim().slice(0, 14),
  })

  const over = []
  root.querySelectorAll('*').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.right > vw + 1 || r.left < -1) over.push(head(el))
  })

  const small = []
  root.querySelectorAll('button, .el-button, a, [role="button"]').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.height < 44 || r.width < 44) small.push({ w: Math.round(r.width), h: Math.round(r.height), ...head(el) })
  })

  const inputs = []
  root.querySelectorAll('.el-input__inner, .el-select__wrapper, .el-textarea__inner').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.height > 0 && r.height < 40) inputs.push({ w: Math.round(r.width), h: Math.round(r.height), ...head(el) })
  })

  const layout = document.querySelector('.admin-layout')
  return JSON.stringify({
    mode,
    vw,
    scrollW: document.documentElement.scrollWidth,
    adminLayoutDirection: layout ? getComputedStyle(layout).flexDirection : null,
    sysPageW: Math.round((document.querySelector('.sys-page') || document.body).getBoundingClientRect().width),
    cards: document.querySelectorAll('.dt-card').length,
    tables: document.querySelectorAll('.data-table__table').length,
    overCount: over.length,
    over: over.slice(0, 10),
    smallCount: small.length,
    small: small.slice(0, 10),
    smallInputCount: inputs.length,
    smallInputs: inputs.slice(0, 5),
  })
})()
