/**
 * 375px 移动端实测（第 2 版）：对越界元素与最小热区元素做祖先链宽度定位。
 */
(() => {
  const vw = innerWidth
  const chain = (el) => {
    const out = []
    let node = el
    let depth = 0
    while (node && node !== document.body && depth < 6) {
      const r = node.getBoundingClientRect()
      out.push({
        tag: node.tagName.toLowerCase(),
        cls: String(node.className || '').slice(0, 46),
        w: Math.round(r.width),
        h: Math.round(r.height),
        left: Math.round(r.left),
        right: Math.round(r.right),
      })
      node = node.parentElement
      depth += 1
    }
    return out
  }

  const over = []
  const small = []
  const root = document.querySelector('.sys-page') || document.body

  root.querySelectorAll('*').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.right > vw + 1 || r.left < -1) over.push({ cls: String(el.className || '').slice(0, 46), right: Math.round(r.right), text: String(el.textContent || '').trim().slice(0, 14), chain: chain(el).slice(0, 4) })
  })

  root.querySelectorAll('button, .el-button, a, [role="button"], .dt-pager__btn').forEach((el) => {
    const r = el.getBoundingClientRect()
    if (r.width <= 0 && r.height <= 0) return
    if (r.height < 44 || r.width < 44) small.push({ cls: String(el.className || '').slice(0, 40), w: Math.round(r.width), h: Math.round(r.height), text: String(el.textContent || '').trim().slice(0, 12), chain: chain(el).slice(0, 4) })
  })

  return JSON.stringify({
    vw,
    scrollW: document.documentElement.scrollWidth,
    overCount: over.length,
    over: over.slice(0, 6),
    smallCount: small.length,
    small: small.slice(0, 6),
  })
})()
