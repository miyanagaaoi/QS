/**
 * 通过 DataTransfer 给 Element Plus 的 el-upload 注入真实文件（浏览器无法用 JS 打开本地文件，
 * 但可以把 dev server 上同源的 .xlsx 取回来构造成 File 再派发 change 事件）。
 */
(async () => {
  const res = await fetch('/src/views/system/__verify__/import_bad.xlsx')
  const buf = await res.arrayBuffer()
  const file = new File([buf], 'import_bad.xlsx', {
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
