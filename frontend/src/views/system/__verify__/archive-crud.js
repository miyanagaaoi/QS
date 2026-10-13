/**
 * 字典维护 → 供货商档案页签：新增 / 编辑 / 停用 全流程（task-12 自检用）
 * 只操作名为 e2e_tmp_archive 的临时档案，测完保持「已停用」，不影响任何真实数据。
 */
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  const setInput = (el, value) => {
    el.value = value
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }
  const toast = () =>
    [...document.querySelectorAll('.el-message')].map((e) => e.innerText.replace(/\n/g, ' '))
  const log = []

  const NAME = 'e2e_tmp_archive'

  // 确保在供货商档案页签
  const tabBtn = [...document.querySelectorAll('.sys-tab')].find((b) =>
    b.textContent.includes('供货商档案'),
  )
  if (tabBtn && !tabBtn.classList.contains('is-on')) {
    tabBtn.click()
    await sleep(2500)
  }

  // ---------- 1) 新增 ----------
  const addBtn = [...document.querySelectorAll('.archive-panel__actions button')].find((b) =>
    b.textContent.includes('新增档案'),
  )
  if (!addBtn) return JSON.stringify({ error: 'NO_ADD_BUTTON' })
  addBtn.click()
  await sleep(800)

  const dlgOf = (title) =>
    [...document.querySelectorAll('.el-dialog')].find(
      (d) => d.offsetParent && String(d.querySelector('.el-dialog__title')?.textContent || '').includes(title),
    )
  let dlg = dlgOf('新增供货商档案')
  if (!dlg) return JSON.stringify({ error: 'NO_CREATE_DIALOG' })
  let inputs = dlg.querySelectorAll('.el-input__inner')
  setInput(inputs[0], NAME) // 名称
  setInput(inputs[1], '91310000TMP0001X') // 信用代码
  setInput(inputs[2], '临时联系人') // 联系人
  setInput(inputs[3], '13800001234') // 电话
  await sleep(200)
  ;[...dlg.querySelectorAll('.el-dialog__footer button')]
    .find((b) => b.textContent.trim().includes('创建档案'))
    .click()
  await sleep(3000)
  log.push({ step: 'create', toast: toast() })

  const findRow = () =>
    [...document.querySelectorAll('.archive-panel .el-table__row')].find((r) =>
      r.innerText.includes(NAME),
    )

  let row = findRow()
  log.push({ step: 'afterCreate', rowFound: !!row, rowText: row?.innerText.replace(/\n/g, ' | ') })

  // ---------- 2) 编辑 ----------
  if (row) {
    ;[...row.querySelectorAll('.sys-ops .el-button')].find((b) => b.textContent.trim() === '编辑').click()
    await sleep(1200)
    dlg = dlgOf('编辑供货商档案')
    if (dlg) {
      inputs = dlg.querySelectorAll('.el-input__inner')
      setInput(inputs[2], '临时联系人已改')
      await sleep(200)
      ;[...dlg.querySelectorAll('.el-dialog__footer button')]
        .find((b) => b.textContent.trim() === '保存')
        .click()
      await sleep(3000)
      log.push({ step: 'edit', toast: toast() })
    } else {
      log.push({ step: 'edit', error: 'NO_EDIT_DIALOG' })
    }
  }

  row = findRow()
  log.push({ step: 'afterEdit', rowText: row?.innerText.replace(/\n/g, ' | ') })

  // ---------- 3) 停用 ----------
  if (row) {
    ;[...row.querySelectorAll('.sys-ops .el-button')].find((b) => b.textContent.trim() === '停用').click()
    await sleep(1200)
    const box = document.querySelector('.el-message-box')
    log.push({ step: 'disableConfirm', title: box?.querySelector('.el-message-box__title')?.textContent })
    const ok = [...document.querySelectorAll('.el-message-box__btns .el-button')].find((b) =>
      b.textContent.includes('确认停用'),
    )
    if (ok) ok.click()
    await sleep(3000)
    log.push({ step: 'disable', toast: toast() })
  }

  row = findRow()
  log.push({ step: 'final', rowText: row?.innerText.replace(/\n/g, ' | ') })

  return JSON.stringify(log)
})()
