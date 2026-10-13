/**
 * 通过真实 UI 新建我方账号（task-10 自检用）
 * window.__CREATE_ARGS = { username, realName, password, turnOn }
 * 返回：开关默认是否关闭、提交前开关状态、提交后的 toast 文案
 */
(async () => {
  const args = window.__CREATE_ARGS || {}
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  const setInput = (el, value) => {
    el.value = value
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // 先切到「我方人员」页签（页签状态可能停在别处）
  const internalTab = [...document.querySelectorAll('.sys-tab')].find((b) =>
    b.textContent.includes('我方人员'),
  )
  if (internalTab && !internalTab.classList.contains('is-on')) {
    internalTab.click()
    await sleep(1500)
  }

  const createBtn = [...document.querySelectorAll('.sys-head__actions button')].find((b) =>
    b.textContent.includes('新建我方账号'),
  )
  if (!createBtn) return JSON.stringify({ error: 'NO_CREATE_BUTTON' })
  createBtn.click()
  await sleep(800)

  const dlg = [...document.querySelectorAll('.el-dialog')].find(
    (d) =>
      d.offsetParent &&
      String(d.querySelector('.el-dialog__title')?.textContent || '').includes('新建我方账号'),
  )
  if (!dlg) return JSON.stringify({ error: 'NO_DIALOG' })

  const inputs = dlg.querySelectorAll('.el-input__inner')
  setInput(inputs[0], args.username)
  setInput(inputs[1], args.realName || '')
  setInput(inputs[2], args.password)

  const sw = dlg.querySelector('.el-switch')
  const switchExists = !!sw
  const defaultOff = sw ? !sw.classList.contains('is-checked') : null
  if (args.turnOn && sw && !sw.classList.contains('is-checked')) sw.click()
  await sleep(300)
  const finalOn = sw ? sw.classList.contains('is-checked') : null

  const submit = [...dlg.querySelectorAll('.el-dialog__footer button')].find((b) =>
    b.textContent.trim().includes('创建账号'),
  )
  if (!submit) return JSON.stringify({ error: 'NO_SUBMIT' })
  submit.click()
  await sleep(3200)

  return JSON.stringify({
    switchExists,
    defaultOff,
    finalOn,
    toast: [...document.querySelectorAll('.el-message')].map((e) => e.innerText.replace(/\n/g, ' ')),
    dialogStillOpen: !!dlg.offsetParent,
  })
})()
