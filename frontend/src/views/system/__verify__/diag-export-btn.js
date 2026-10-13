/**
 * 「导出错误报告」按钮诊断（task-6 自检用）
 * 依次排除：按钮是否 disabled / 是否有 Vue 事件处理 / 点击后是否有 loading / 是否发出 XHR / 是否弹 Toast
 */
(async () => {
  const btns = [...document.querySelectorAll('.el-dialog__footer button')]
  const btn = btns.find((b) => b.textContent.trim() === '导出错误报告')
  const out = {
    btnFound: !!btn,
    disabled: btn ? btn.disabled : null,
    ariaDisabled: btn ? btn.getAttribute('aria-disabled') : null,
    cls: btn ? btn.className : null,
    fileNameText: document.querySelector('.up-file__name')?.textContent || null,
    // Vue 3 的事件 invoker 挂在 Symbol('_vei') 上，字符串属性取不到
    veiSymbols: btn ? Object.getOwnPropertySymbols(btn).map((s) => s.toString()) : null,
    otherFooterBtns: btns.map((b) => b.textContent.trim()),
  }

  if (!btn) return JSON.stringify(out)

  // 安装 XHR 观测
  if (!window.__patched2) {
    window.__reqs = []
    const O = XMLHttpRequest.prototype.open
    const S = XMLHttpRequest.prototype.send
    XMLHttpRequest.prototype.open = function (m, u) {
      this.__u = m + ' ' + u
      window.__reqs.push(this.__u)
      return O.apply(this, arguments)
    }
    XMLHttpRequest.prototype.send = function () {
      this.addEventListener('load', function () {
        ;(window.__reqStatus = window.__reqStatus || []).push(this.__u + ' -> HTTP ' + this.status)
      })
      return S.apply(this, arguments)
    }
    window.__patched2 = true
  }

  const loadingSeen = []
  const watcher = setInterval(() => {
    const b = [...document.querySelectorAll('.el-dialog__footer button')].find(
      (x) => x.textContent.trim() === '导出错误报告',
    )
    if (b && b.classList.contains('is-loading')) loadingSeen.push(Date.now())
  }, 40)

  const before = { reqs: window.__reqs.length, toasts: document.querySelectorAll('.el-message').length }

  btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))

  await new Promise((r) => setTimeout(r, 2500))
  clearInterval(watcher)

  out.loadingSeen = loadingSeen.length
  out.newReqs = window.__reqs.slice(before.reqs)
  out.reqStatus = window.__reqStatus || []
  out.toasts = [...document.querySelectorAll('.el-message')].map((e) => e.innerText.replace(/\n/g, ' '))
  out.newToasts = out.toasts.length - before.toasts
  return JSON.stringify(out)
})()
