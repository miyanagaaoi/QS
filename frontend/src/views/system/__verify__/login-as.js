/**
 * UI 登录（task-10 自检用）
 * window.__LOGIN_ARGS = { username, password }
 * 返回登录后的落地 URL 与提示，用于验证「关闭开关 → 不被强制改密 / 开启 → 40101 强制改密」
 *
 * 注意：调用方必须**先**清 localStorage 并导航到 /login，再设置 __LOGIN_ARGS 并执行本脚本。
 * 本脚本内部不做导航（导航会销毁执行上下文，导致参数丢失）。
 */
(async () => {
  const args = window.__LOGIN_ARGS || {}
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  const setInput = (el, value) => {
    el.value = value
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  if (location.pathname !== '/login') {
    return JSON.stringify({ error: 'NOT_ON_LOGIN', url: location.pathname })
  }

  // 等表单渲染出来
  for (let i = 0; i < 10; i += 1) {
    if (document.querySelectorAll('.el-input__inner').length >= 2) break
    await sleep(500)
  }

  const inputs = document.querySelectorAll('.el-input__inner')
  if (inputs.length < 2) return JSON.stringify({ error: 'NO_INPUTS', url: location.pathname })
  setInput(inputs[0], args.username)
  setInput(inputs[1], args.password)
  await sleep(200)

  const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '登录')
  if (!btn) return JSON.stringify({ error: 'NO_BTN' })
  btn.click()
  await sleep(4000)

  return JSON.stringify({
    account: args.username,
    url: location.pathname + location.search,
    title: document.title,
    toast: [...document.querySelectorAll('.el-message')].map((e) => e.innerText.replace(/\n/g, ' ')),
    formErrors: [...document.querySelectorAll('.el-form-item__error')].map((e) => e.textContent),
  })
})()

