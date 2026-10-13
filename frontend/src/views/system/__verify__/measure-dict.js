/**
 * 375px 收口实测（task-6 自检用）：
 *  1. 徽标是否被所属卡片裁切（fe-base 报的是这个，必须按元素量，scrollWidth 检测不到）
 *  2. 最小按钮热区
 *  3. 页面横向溢出 / 卡片数
 * window.__MEASURE_MODE='fix' 时先把 .admin-layout 的 flex-direction 改为 column
 * （模拟 AdminLayout 手机端布局修好后的状态；只改运行时样式，不动任何源文件）。
 */
(() => {
  const mode = window.__MEASURE_MODE || 'raw'
  if (mode === 'fix') {
    const layout = document.querySelector('.admin-layout')
    if (layout) layout.style.flexDirection = 'column'
  }

  const vw = innerWidth
  const root = document.querySelector('.sys-page') || document.body

  const clipped = []
  root.querySelectorAll('.dt-card .status-badge').forEach((b) => {
    const card = b.closest('.dt-card')
    const field = b.closest('.dt-card__field')
    const br = b.getBoundingClientRect()
    const cr = card.getBoundingClientRect()
    const fr = field ? field.getBoundingClientRect() : null
    const overflowCard = Math.round(br.right - (cr.right - 1))
    const overflowField = fr ? Math.round(br.right - fr.right) : null
    if (overflowCard > 0 || (overflowField !== null && overflowField > 0)) {
      clipped.push({
        text: b.textContent.trim(),
        badgeW: Math.round(br.width),
        cardRight: Math.round(cr.right),
        badgeRight: Math.round(br.right),
        overflowCard,
        overflowField,
      })
    }
  })

  const minBtn = { w: 9999, h: 9999, text: '' }
  const under44 = []
  root.querySelectorAll('button, .el-button, a, [role="button"]').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    const info = {
      cls: String(el.className || '').slice(0, 38),
      w: Math.round(r.width),
      h: Math.round(r.height),
      text: String(el.textContent || '').trim().slice(0, 14),
    }
    if (r.width < minBtn.w || r.height < minBtn.h) Object.assign(minBtn, info)
    if (r.height < 44 || r.width < 44) under44.push(info)
  })

  const layout = document.querySelector('.admin-layout')
  return JSON.stringify({
    mode,
    vw,
    scrollW: document.documentElement.scrollWidth,
    adminLayoutDirection: layout ? getComputedStyle(layout).flexDirection : null,
    sysPageW: Math.round(root.getBoundingClientRect().width),
    cards: document.querySelectorAll('.dt-card').length,
    badgesInCards: root.querySelectorAll('.dt-card .status-badge').length,
    clippedCount: clipped.length,
    clipped: clipped.slice(0, 6),
    minBtn,
    under44Count: under44.length,
    under44: under44.slice(0, 6),
  })
})()
