/**
 * 供货商报价填报 —— 逻辑与接口契约自检脚本（node 直接运行，不依赖浏览器）
 * ===========================================================================
 *   cd frontend && node src/views/supplier/__verify__/verify_quote_contract.mjs
 *
 * 两部分：
 *  A. 离线断言：金额清洗 / 已填判定 / 分段 / payload 组装 / 草稿 / 只读 / 倒计时
 *  B. 在线契约：用真实账号打真实接口，逐字段核对 quoteModel 的取数代码
 *     - GET /supplier/rfqs           列表字段名
 *     - GET /supplier/rfqs/{id}      详情 + lines[].quote 字段名
 *     - deadline(北京时间 naive) 与 remaining_seconds 同一基准（前端按本地解析自洽）
 *       同时校验本机时区为 UTC+8 —— 这是"naive 按本地解释"的前提
 *     - PUT /supplier/rfqs/{id}/quotes 的错误分支（不写库：提交校验/截止锁定/参数校验）
 *     - POST /supplier/attachments    附件成功响应字段名（会留下一个 1×1 PNG 与一条 audit）
 */
import assert from 'node:assert/strict'

import {
  DEFAULT_TAX_RATE,
  SEGMENT_SIZE,
  applyDraft,
  buildSavePayload,
  buildSegments,
  computePriceExclTax,
  createCountdown,
  createRow,
  createRows,
  draftHasContent,
  formatRemainingCompact,
  isRowDirty,
  isRowFilled,
  parseServerDateTime,
  remainingTone,
  resolveReadonly,
  sanitizeDecimal3,
  sanitizeInt,
  sanitizePrice,
  segmentUnfilledCount,
  sumFilled,
  toDraft,
  unfilledSeqs,
  validateForSubmit,
  validatePrice,
} from '../quoteModel.js'

const BASE = process.env.XJ_API_BASE || 'http://127.0.0.1:8000/api'
const USERNAME = process.env.XJ_SUPPLIER_USER || 'hengxin_wenju'
const PASSWORD = process.env.XJ_SUPPLIER_PASS || 'supplier123'

let passCount = 0
let failCount = 0
const failures = []

function check(name, fn) {
  try {
    fn()
    passCount += 1
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failCount += 1
    failures.push(`${name}: ${error.message}`)
    console.log(`  ✗ ${name}\n      ${error.message}`)
  }
}

async function checkAsync(name, fn) {
  try {
    await fn()
    passCount += 1
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failCount += 1
    failures.push(`${name}: ${error.message}`)
    console.log(`  ✗ ${name}\n      ${error.message}`)
  }
}

function section(title) {
  console.log(`\n${title}`)
}

// ===========================================================================
// A. 离线逻辑
// ===========================================================================
section('A. 离线逻辑（quoteModel.js）')

check('单价清洗：过滤非法字符 / 限 2 位小数 / 限 7 位整数', () => {
  assert.equal(sanitizePrice('12.345'), '12.34')
  assert.equal(sanitizePrice('1.2.3'), '1.23')
  assert.equal(sanitizePrice('abc'), '')
  assert.equal(sanitizePrice('12345678.9'), '1234567.9')
  assert.equal(sanitizePrice('12345678'), '1234567')
  assert.equal(sanitizePrice('.5'), '0.5')
  assert.equal(sanitizePrice('0'), '0')
  assert.equal(sanitizePrice(''), '')
})

check('MOQ / 交期清洗', () => {
  assert.equal(sanitizeDecimal3('1.23456'), '1.234')
  assert.equal(sanitizeDecimal3(''), '')
  assert.equal(sanitizeInt('12a3'), '123')
  assert.equal(sanitizeInt('99999'), '3650')
  assert.equal(sanitizeInt(''), '')
})

check('单价校验：空=未填，「0」是有效报价', () => {
  assert.deepEqual(validatePrice(''), { filled: false, ok: true, message: '' })
  assert.equal(validatePrice('0').filled, true)
  assert.equal(validatePrice('0').ok, true)
  assert.equal(validatePrice('9999999.99').ok, true)
  assert.equal(validatePrice('99999999').ok, false)
  assert.equal(validatePrice('1.234').ok, false)
  assert.equal(validatePrice('.').ok, false)
})

check('已填判定：0 算已填，空不算', () => {
  assert.equal(isRowFilled({ priceInclTax: '0' }), true)
  assert.equal(isRowFilled({ priceInclTax: '' }), false)
  assert.equal(isRowFilled({ priceInclTax: '  ' }), false)
  assert.equal(isRowFilled({ priceInclTax: '1.2.3' }), false)
})

check('不含税单价计算与后端 calc_price_excl_tax 一致', () => {
  assert.equal(computePriceExclTax({ priceInclTax: '113', taxIncluded: true, taxRate: '0.13' }), '100.00')
  assert.equal(computePriceExclTax({ priceInclTax: '6.8', taxIncluded: true, taxRate: '0.13' }), '6.02')
  assert.equal(computePriceExclTax({ priceInclTax: '10', taxIncluded: false, taxRate: '0.13' }), '10.00')
  assert.equal(computePriceExclTax({ priceInclTax: '', taxIncluded: true, taxRate: '0.13' }), '')
})

check('分段：43 行 → 5 段，最后一段 41~43；8 行 → 1 段', () => {
  const segs = buildSegments(43)
  assert.equal(segs.length, 5)
  assert.deepEqual(segs[0], { index: 0, from: 1, to: 10, label: '1~10' })
  assert.deepEqual(segs[4], { index: 4, from: 41, to: 43, label: '41~43' })
  assert.equal(buildSegments(8).length, 1)
  assert.equal(buildSegments(0).length, 0)
  assert.equal(SEGMENT_SIZE, 10)
})

check('段内未填统计 + 整单统计（底部计数按整单）', () => {
  const rows = [1, 2, 3, 4, 5, 6].map((seq) =>
    createRow({ line_uid: `u${seq}`, seq, material_name: `料${seq}`, unit: '个', quantity: '10', quote: null }),
  )
  rows[1].priceInclTax = '5'
  assert.equal(segmentUnfilledCount(rows, 1, 3), 2)
  assert.equal(segmentUnfilledCount(rows, 4, 6), 3)
  assert.deepEqual(sumFilled(rows), { filled: 1, total: 6, unfilled: 5 })
  assert.deepEqual(unfilledSeqs(rows), [1, 3, 4, 5, 6])
})

check('行模型：只读物料字段 + 可写报价字段 + dirty 基准', () => {
  const row = createRow({
    line_uid: 'abc',
    seq: 1,
    material_name: '订书机',
    spec: '得力，小',
    unit: '个',
    quantity: '40.000',
    quote: null,
  })
  assert.equal(row.materialName, '订书机')
  assert.equal(row.quantity, '40.000')
  assert.equal(row.priceInclTax, '')
  assert.equal(row.taxIncluded, true)
  assert.equal(row.taxRate, DEFAULT_TAX_RATE)
  assert.equal(row.attachments.length, 0)
  assert.equal(isRowDirty(row), false)
  row.priceInclTax = '113.00'
  assert.equal(isRowDirty(row), true)
})

check('已保存报价回填（quote 字段名与 schemas.QuoteLineOut 对齐）', () => {
  const row = createRow({
    line_uid: 'abc',
    seq: 1,
    material_name: '订书机',
    spec: '得力，小',
    unit: '个',
    quantity: '40.000',
    quote: {
      line_uid: 'abc',
      price_incl_tax: '95.00',
      tax_included: false,
      tax_rate: '0.1300',
      price_excl_tax: '84.07',
      moq: '1.000',
      lead_time_days: 5,
      arrival_date: '2026-10-20',
      remark: null,
      attachments: [{ filename: 'a.jpg', original_name: 'a.jpg', size: 100, url: '/api/supplier/attachments/a.jpg' }],
    },
  })
  assert.equal(row.priceInclTax, '95.00')
  assert.equal(row.taxIncluded, false)
  assert.equal(row.taxRate, '0.1300')
  assert.equal(row.moq, '1.000')
  assert.equal(row.leadTimeDays, '5')
  assert.equal(row.arrivalDate, '2026-10-20')
  assert.equal(row.attachments.length, 1)
  assert.equal(isRowDirty(row), false)
})

check('payload：只发 dirty 行，字段名严格对齐 QuoteLineIn', () => {
  const rows = createRows({
    lines: [
      { line_uid: 'l1', seq: 1, material_name: 'A', spec: null, unit: '个', quantity: '10', quote: null },
      { line_uid: 'l2', seq: 2, material_name: 'B', spec: null, unit: '个', quantity: '20', quote: null },
    ],
  })
  assert.deepEqual(buildSavePayload(rows).lines, [], '未改动时不应发送任何行（否则会白写历史/清空服务端值）')

  rows[0].priceInclTax = '1.5'
  rows[0].taxIncluded = false
  rows[0].taxRate = '0.13'
  rows[0].moq = '5'
  rows[0].leadTimeDays = '3'
  rows[0].arrivalDate = '2026-11-01'
  rows[0].remark = '备注'
  rows[0].attachments = [{ filename: 'x.jpg', original_name: 'x.jpg', size: 9, url: '/u', _preview: 'blob:local' }]

  const payload = buildSavePayload(rows, { submit: true, expectedUpdatedAt: '2026-10-13T12:24:02.902177' })
  assert.deepEqual(Object.keys(payload).sort(), ['expected_updated_at', 'lines', 'submit'])
  assert.equal(payload.submit, true)
  assert.equal(payload.lines.length, 1)
  const line = payload.lines[0]
  assert.deepEqual(Object.keys(line).sort(), [
    'arrival_date',
    'attachments',
    'lead_time_days',
    'line_uid',
    'moq',
    'price_incl_tax',
    'remark',
    'tax_included',
    'tax_rate',
  ])
  assert.equal(line.line_uid, 'l1')
  assert.equal(line.price_incl_tax, '1.5')
  assert.equal(line.tax_included, false)
  assert.equal(line.lead_time_days, 3)
  assert.equal(line.arrival_date, '2026-11-01')
  // 前端私有字段 _preview 不得出现在请求体里
  assert.deepEqual(Object.keys(line.attachments[0]).sort(), ['filename', 'original_name', 'size', 'url'])

  // 清空原本有值的行 → 发送 null 以便服务端清空（而不是默默保留旧值）
  rows[1].priceInclTax = ''
  assert.equal(isRowDirty(rows[1]), false, '未填且未改动 → 不算 dirty')
  rows[0].priceInclTax = ''
  const clearPayload = buildSavePayload(rows, { submit: false })
  const cleared = clearPayload.lines.find((item) => item.line_uid === 'l1')
  assert.equal(cleared.price_incl_tax, null)
})

check('提交前本地校验：缺价阻断 + 缺税率', () => {
  const rows = createRows({
    lines: [
      { line_uid: 'l1', seq: 1, material_name: 'A', spec: null, unit: '个', quantity: '10', quote: null },
      { line_uid: 'l2', seq: 2, material_name: 'B', spec: null, unit: '个', quantity: '20', quote: null },
    ],
  })
  rows[0].priceInclTax = '2'
  const result = validateForSubmit(rows)
  assert.equal(result.ok, false)
  assert.deepEqual(result.missing, [2])
  assert.equal(result.problems[0].type, 'missing_price')
  rows[1].priceInclTax = '3'
  assert.equal(validateForSubmit(rows).ok, true)
})

check('草稿：只存 dirty 行；dirty 归零后无草稿内容；回填只覆盖对应行', () => {
  const rows = createRows({
    lines: [
      { line_uid: 'l1', seq: 1, material_name: 'A', spec: null, unit: '个', quantity: '10', quote: null },
      { line_uid: 'l2', seq: 2, material_name: 'B', spec: null, unit: '个', quantity: '20', quote: null },
    ],
  })
  assert.equal(draftHasContent(toDraft(rows, 'base')), false)
  rows[0].priceInclTax = '7.7'
  const draft = toDraft(rows, 'base')
  assert.equal(draft.lines.length, 1)
  assert.equal(draftHasContent(draft), true)

  const fresh = createRows({
    lines: [
      { line_uid: 'l1', seq: 1, material_name: 'A', spec: null, unit: '个', quantity: '10', quote: null },
      { line_uid: 'l2', seq: 2, material_name: 'B', spec: null, unit: '个', quantity: '20', quote: null },
    ],
  })
  applyDraft(fresh, draft)
  assert.equal(fresh[0].priceInclTax, '7.7')
  assert.equal(fresh[0].materialName, 'A')
  assert.equal(fresh[1].priceInclTax, '')
})

check('只读判定：后端标记 / closed / 剩余为 0 都转只读', () => {
  assert.equal(resolveReadonly({ readonly: false, status: 'published' }, 100), false)
  assert.equal(resolveReadonly({ readonly: true, status: 'published' }, 100), true)
  assert.equal(resolveReadonly({ readonly: false, status: 'closed' }, 100), true)
  assert.equal(resolveReadonly({ readonly: false, status: 'published' }, 0), true)
  assert.equal(resolveReadonly({ readonly: false, status: 'published' }, -30), true)
})

check('紧急度与紧凑倒计时文案（设计稿：<24h 危险色）', () => {
  assert.equal(remainingTone(6 * 3600), 'danger')
  assert.equal(remainingTone(52 * 3600), 'warn')
  assert.equal(remainingTone(3 * 86400), 'muted')
  assert.equal(remainingTone(0), 'closed')
  assert.equal(formatRemainingCompact(2 * 86400 + 4 * 3600), '2天4时')
  assert.equal(formatRemainingCompact(3 * 3600 + 12 * 60), '3时12分')
  assert.equal(formatRemainingCompact(0), '已截止')
})

check('倒计时时钟以后端秒数为基准做本地漂移', () => {
  const clock = createCountdown(120)
  const left = clock.left()
  assert.ok(left <= 120 && left >= 118, `期望 ≈120，实际 ${left}`)
  assert.equal(createCountdown(null).left(), null)
})

check('服务端时间解析：naive=北京时间（按本地解释），带时区后缀仍按时区换算', () => {
  // 口径（2026-10 统一）：后端返回北京时间 naive → 直接按本地字段解释。
  // 下面断言只用「本地字段」与「UTC 毫秒」两边比，不依赖跑脚本的机器时区。
  const naive = parseServerDateTime('2026-10-15T18:00:00')
  assert.equal(naive.getFullYear(), 2026)
  assert.equal(naive.getMonth(), 9)
  assert.equal(naive.getDate(), 15)
  assert.equal(naive.getHours(), 18, 'naive 字符串必须按本地时间解释（旧实现会多减 8 小时）')
  assert.equal(naive.getMinutes(), 0)

  // 小数秒（后端真实格式 "…T16:15:01.662136"）不能被丢掉
  const frac = parseServerDateTime('2026-10-15T18:00:00.662136')
  assert.equal(frac.getHours(), 18)
  assert.equal(frac.getMilliseconds(), 662)

  // 仅日期
  const dateOnly = parseServerDateTime('2026-10-15')
  assert.equal(dateOnly.getDate(), 15)
  assert.equal(dateOnly.getHours(), 0)

  // 带 Z → 按 UTC 解释（判据用 UTC 毫秒，与机器时区无关）
  assert.equal(parseServerDateTime('2026-10-15T10:00:00Z').getTime(), Date.UTC(2026, 9, 15, 10, 0, 0))

  // 带 +08:00 → 18:00(+08:00) 就是 10:00Z
  assert.equal(
    parseServerDateTime('2026-10-15T18:00:00+08:00').getTime(),
    Date.UTC(2026, 9, 15, 10, 0, 0),
  )
  // 带 -05:00 → 05:00(-05:00) 就是 10:00Z
  assert.equal(
    parseServerDateTime('2026-10-15T05:00:00-05:00').getTime(),
    Date.UTC(2026, 9, 15, 10, 0, 0),
  )
  assert.equal(parseServerDateTime(null), null)
})

// ===========================================================================
// B. 在线契约（真实后端）
// ===========================================================================
section(`B. 在线契约（${BASE}）`)

let token = ''

await checkAsync('登录供货商账号取 token', async () => {
  const response = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USERNAME, password: PASSWORD }),
  })
  const body = await response.json()
  assert.equal(body.code, 0, `登录失败：${body.message}`)
  token = body.data.token
  assert.ok(token, 'token 为空')
})

async function api(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  })
  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  return { status: response.status, body }
}

let listItems = []
let openItem = null
let detail = null
let quotedDetail = null
let closedDetail = null

await checkAsync('GET /supplier/rfqs 列表字段名与 SupplierRfqListItem 一致', async () => {
  const { status, body } = await api('/supplier/rfqs?page=1&page_size=100')
  assert.equal(status, 200)
  assert.equal(body.code, 0)
  assert.ok(Array.isArray(body.data.items), 'data.items 不是数组')
  assert.ok(body.data.meta && typeof body.data.meta.total === 'number', '缺少 meta')
  listItems = body.data.items
  assert.ok(listItems.length > 0, '演示数据为空，无法继续')
  const expected = [
    'rfq_id',
    'rfq_no',
    'title',
    'project',
    'deadline',
    'remaining_seconds',
    'status',
    'my_status',
    'line_count',
    'quoted_line_count',
    'last_saved_at',
    'submitted_at',
  ]
  listItems.forEach((item) => {
    expected.forEach((key) => assert.ok(key in item, `列表项缺少字段 ${key}`))
    // 越权红线：列表项不得出现任何他方报价/最低价字段
    ;['lowest_price', 'best_price', 'min_price', 'supplier_count', 'other_quotes'].forEach((key) =>
      assert.ok(!(key in item), `列表项出现越权字段 ${key}`),
    )
  })
  openItem = listItems.find((item) => item.status === 'published' && item.my_status !== 'quoted')
  assert.ok(openItem, '找不到可分派的进行中单据用于验证')
})

await checkAsync('deadline(北京时间 naive) 与 remaining_seconds 同一基准 + 本机时区应为 UTC+8', async () => {
  // 只取「未截止」的单据：后端对已截止单据的 remaining_seconds 会夹到 0，无法比对
  const item = listItems.find((row) => Number(row.remaining_seconds) > 600)
  assert.ok(item, '找不到未截止单据用于时区验证')
  const tzOffset = -new Date().getTimezoneOffset() / 60
  // 前提校验（不是解析 bug）：naive 按本地解释要求设备与后端同处东八区。
  // 若这里失败，说明跑脚本/用户的设备时区不是 UTC+8，页面上的"截止时间"会偏，
  // 但倒计时（用 remaining_seconds）仍然正确。
  assert.equal(
    tzOffset,
    8,
    `本机时区为 UTC+${tzOffset}，非东八区：naive 时间按本地解释会偏 ${8 - tzOffset} 小时`,
  )
  const left = (parseServerDateTime(item.deadline).getTime() - Date.now()) / 1000
  const diff = Math.abs(left - Number(item.remaining_seconds))
  assert.ok(
    diff < 180,
    `${item.rfq_no}: 按本地解析 deadline 与 remaining_seconds 相差 ${Math.round(diff)}s（说明前后端时间口径又不一致了）`,
  )
  console.log(
    `      ${item.rfq_no}: remaining=${item.remaining_seconds}s，本地解析 ${Math.round(left)}s，差 ${Math.round(diff)}s，本机时区 UTC+${tzOffset}`,
  )
})

await checkAsync('GET /supplier/rfqs/{id} 详情字段名与 SupplierRfqDetail 一致', async () => {
  const { status, body } = await api(`/supplier/rfqs/${openItem.rfq_id}`)
  assert.equal(status, 200)
  detail = body.data
  ;['rfq_id', 'rfq_no', 'title', 'project', 'remark', 'deadline', 'remaining_seconds', 'status', 'my_status', 'readonly', 'line_count', 'quoted_line_count', 'submitted_at', 'updated_at', 'lines'].forEach(
    (key) => assert.ok(key in detail, `详情缺少字段 ${key}`),
  )
  assert.ok(Array.isArray(detail.lines))
  const line = detail.lines[0]
  ;['line_uid', 'seq', 'material_name', 'spec', 'unit', 'quantity', 'quote'].forEach((key) =>
    assert.ok(key in line, `明细行缺少字段 ${key}`),
  )
  assert.equal(typeof line.material_name, 'string')
  assert.equal(typeof line.unit, 'string')
  // 只读物料信息必须齐全，页面才不用猜
  detail.lines.forEach((item) => {
    assert.ok(item.line_uid && item.material_name && item.unit, ' 物料只读字段缺失')
    assert.ok(Number(item.seq) > 0, 'seq 非法')
  })
})

await checkAsync('已报价单据的 lines[].quote 字段名与 QuoteLineOut 一致', async () => {
  const quoted = listItems.find((item) => item.my_status === 'quoted')
  if (!quoted) {
    console.log('      （当前账号没有已报价单据，跳过）')
    return
  }
  const { body } = await api(`/supplier/rfqs/${quoted.rfq_id}`)
  quotedDetail = body.data
  const withQuote = quotedDetail.lines.find((line) => line.quote)
  assert.ok(withQuote, '已报价单据却没有任何 quote')
  ;['line_uid', 'price_incl_tax', 'tax_included', 'tax_rate', 'price_excl_tax', 'moq', 'lead_time_days', 'arrival_date', 'remark', 'attachments'].forEach(
    (key) => assert.ok(key in withQuote.quote, `quote 缺少字段 ${key}`),
  )
  // 取数代码能正确回填
  const rows = createRows(quotedDetail)
  const row = rows.find((item) => item.lineUid === withQuote.line_uid)
  assert.equal(row.priceInclTax, String(withQuote.quote.price_incl_tax ?? ''))
  assert.equal(row.leadTimeDays, String(withQuote.quote.lead_time_days ?? ''))
  assert.equal(row.arrivalDate, String(withQuote.quote.arrival_date ?? ''))
  assert.equal(isRowDirty(row), false, '服务端数据回填后不应是 dirty')
  assert.equal(buildSavePayload(rows).lines.length, 0, '刚打开页面不应产生任何要提交的行')
})

await checkAsync('已截止单据 readonly=true（底部栏据此替换为说明条）', async () => {
  const closed = listItems.find((item) => item.status === 'closed')
  if (!closed) {
    console.log('      （当前账号没有已截止单据，跳过）')
    return
  }
  const { body } = await api(`/supplier/rfqs/${closed.rfq_id}`)
  closedDetail = body.data
  assert.equal(closedDetail.readonly, true)
  assert.equal(resolveReadonly(closedDetail, closedDetail.remaining_seconds), true)
})

await checkAsync('PUT /quotes 提交校验分支：缺价返回 40001（不写库）', async () => {
  const target = listItems.find((item) => item.status === 'published' && item.quoted_line_count === 0)
  if (!target) {
    console.log('      （没有 0 行已填的进行中单据，跳过）')
    return
  }
  const { status, body } = await api(`/supplier/rfqs/${target.rfq_id}/quotes`, {
    method: 'PUT',
    body: JSON.stringify({ lines: [], submit: true }),
  })
  assert.equal(body.code, 40001, `期望 40001，实际 ${body.code}（${body.message}）`)
  assert.match(body.message, /提交失败/)
  assert.match(body.message, /第\d+行/)
  assert.ok(status >= 400, `期望 HTTP 4xx，实际 ${status}`)
})

await checkAsync('PUT /quotes 参数校验：price_incl_tax=-1 → 40001 且 loc 证明字段名被正确解析', async () => {
  const lines = detail.lines.slice(0, 1).map((line) => ({ line_uid: line.line_uid, price_incl_tax: '-1' }))
  const { body } = await api(`/supplier/rfqs/${detail.rfq_id}/quotes`, {
    method: 'PUT',
    body: JSON.stringify({ lines }),
  })
  assert.equal(body.code, 40001)
  assert.equal(body.data.errors[0].loc, 'body.lines.0.price_incl_tax')
})

await checkAsync('PUT /quotes 截止锁定：closed 单据 → 40301（页面据此转只读）', async () => {
  const closed = listItems.find((item) => item.status === 'closed')
  if (!closed) {
    console.log('      （没有已截止单据，跳过）')
    return
  }
  const { body } = await api(`/supplier/rfqs/${closed.rfq_id}/quotes`, {
    method: 'PUT',
    body: JSON.stringify({ lines: [], submit: false }),
  })
  assert.equal(body.code, 40301, `期望 40301，实际 ${body.code}`)
  assert.match(body.message, /截止/)
})

await checkAsync('POST /rfqs/{id}/submit 是 PUT /quotes 的别名（强制 submit=True）', async () => {
  const target = listItems.find((item) => item.status === 'published' && item.quoted_line_count === 0)
  if (!target) {
    console.log('      （没有 0 行已填的进行中单据，跳过）')
    return
  }
  // body 里显式传 submit:false，但别名端点会强制 submit=True → 应返回提交校验错误
  const { body } = await api(`/supplier/rfqs/${target.rfq_id}/submit`, {
    method: 'POST',
    body: JSON.stringify({ lines: [], submit: false }),
  })
  assert.equal(body.code, 40001, `期望 40001（提交校验），实际 ${body.code}：${body.message}`)
  assert.match(body.message, /提交失败/)
})

await checkAsync('越权：访问未分派单据返回 40300/40400', async () => {
  const { body } = await api('/supplier/rfqs/999999')
  assert.ok([40300, 40400].includes(body.code), `期望 40300/40400，实际 ${body.code}`)
})

await checkAsync('POST /supplier/attachments 契约回显 4 个字段（前端用它拼 attachments）', async () => {
  const bad = new FormData()
  bad.append('file', new Blob([Buffer.from('x')], { type: 'text/plain' }), 'verify.txt')
  const badResponse = await fetch(`${BASE}/supplier/attachments`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: bad,
  })
  const badBody = await badResponse.json()
  assert.equal(badBody.code, 40001, '非法扩展名应被拒绝')
  assert.match(badBody.message, /不支持的文件类型/)

  // 1×1 PNG（最小的合法图片）
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AP//AAAA//8DAANl0Ks8AAAAAElFTkSuQmCC',
    'base64',
  )
  const form = new FormData()
  form.append('file', new Blob([png], { type: 'image/png' }), 'verify-1x1.png')
  const response = await fetch(`${BASE}/supplier/attachments`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  const body = await response.json()
  assert.equal(body.code, 0, `上传失败：${body.message}`)
  ;['filename', 'original_name', 'size', 'url'].forEach((key) =>
    assert.ok(key in body.data, `附件响应缺少字段 ${key}`),
  )
  assert.equal(body.data.original_name, 'verify-1x1.png')
  assert.match(body.data.url, /^\/api\/supplier\/attachments\//)
  console.log(`      上传回显：${body.data.url}（${body.data.size} 字节，服务端留档）`)
})

await checkAsync('历史报价接口字段（QuoteHistoryItem）与 quoteModel 无关但供后续页面复用', async () => {
  const { body } = await api('/supplier/quotes/history?page=1&page_size=3')
  if (!body?.data?.items?.length) {
    console.log('      （暂无改价历史，跳过）')
    return
  }
  ;['line_uid', 'version', 'action', 'changed_fields', 'snapshot', 'operated_by_name', 'created_at'].forEach((key) =>
    assert.ok(key in body.data.items[0], `历史项缺少字段 ${key}`),
  )
})

// ===========================================================================
console.log(`\n${'='.repeat(64)}`)
console.log(`通过 ${passCount} 项，失败 ${failCount} 项`)
if (failCount) {
  console.log('\n失败明细：')
  failures.forEach((item) => console.log(`  - ${item}`))
}
console.log('='.repeat(64))
process.exit(failCount ? 1 : 0)
