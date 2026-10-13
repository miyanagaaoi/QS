/**
 * 注入「全部校验通过」的 xlsx（task-6 自检用）：验证「确认导入」成功链路。
 */
(async () => {
  const res = await fetch('/src/views/system/__verify__/import_good.xlsx')
  const buf = await res.arrayBuffer()
  const file = new File([buf], 'import_good.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const dt = new DataTransfer()
  dt.items.add(file)
  const input = document.querySelector('.up input[type="file"]')
  if (!input) return 'NO_INPUT'
  input.files = dt.files
  input.dispatchEvent(new Event('change', { bubbles: true }))
  return `dispatched bytes=${buf.byteLength}`
})()
