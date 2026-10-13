<script setup>
/**
 * QuoteTable — 平板 / 桌面表格形态（设计稿 03-5 / PRD 10.2）
 * ---------------------------------------------------------------------------
 * 768~1199px（平板）：保留表格，列收敛为 6 列
 *   物料 | 需求 | 含税单价 * | 税率 | 交期(天) | 到货日期
 *   —— 设计稿把这 6 列之外的 MOQ / 行备注 / 附件收进行内（这里放到 ≥1200 的扩展列）
 * ≥1200px（桌面）：恢复全列（+ 不含税单价 / MOQ / 行备注 / 行附件）
 *
 * 两处与设计稿的有意取舍（已在报告中说明）：
 *  1. 输入框字号用 16px（PRD 10.4「输入框 ≥16px」是硬约束，iOS/iPadOS 聚焦会自动放大页面）；
 *     桌面（鼠标键盘为主）用 14px，避免 10 列表格过于松散。
 *  2. 是否含税是必填字段，改用「物料列下方的小开关」承载，不再额外占列
 *     （设计稿平板表格没有这一列，但字段不能丢）。
 * 宽表在自身内部横向滚动（PRD 10.1 允许），页面整体不横向滚动。
 */
import { computed } from 'vue'

import { TAX_RATE_OPTIONS, computePriceExclTax, isRowFilled, rowWarnings, sanitizeDecimal3, sanitizeInt, sanitizePrice, validatePrice } from '../quoteModel'
import AttachmentPicker from './AttachmentPicker.vue'

defineOptions({ name: 'QuoteTable' })

const props = defineProps({
  rows: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  /** tablet（6 列） | desktop（全列） */
  variant: { type: String, default: 'tablet' },
  minDate: { type: String, default: '' },
  maxDate: { type: String, default: '' },
})

const emit = defineEmits(['patch'])

const isDesktop = computed(() => props.variant === 'desktop')

function patch(row, key, value) {
  emit('patch', { row, patch: { [key]: value } })
}

function priceError(row) {
  const state = validatePrice(row.priceInclTax)
  return state.ok ? '' : state.message
}

function onPriceInput(row, event) {
  patch(row, 'priceInclTax', sanitizePrice(event.target.value))
}

function onMoqInput(row, event) {
  patch(row, 'moq', sanitizeDecimal3(event.target.value))
}

function onLeadInput(row, event) {
  patch(row, 'leadTimeDays', sanitizeInt(event.target.value))
}

function onRemarkInput(row, event) {
  patch(row, 'remark', String(event.target.value || '').slice(0, 200))
}

function quantityText(row) {
  const n = Number(String(row.quantity ?? '').trim())
  if (!Number.isFinite(n)) return String(row.quantity ?? '—')
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 }).format(n)
}

function warningsOf(row) {
  return rowWarnings(row).join('；')
}
</script>

<template>
  <div class="qt-wrap">
    <table class="qt" :class="{ 'is-desktop': isDesktop }">
      <thead>
        <tr>
          <th class="qt__th-material">物料</th>
          <th class="qt__th-qty">需求</th>
          <th class="qt__th-price">含税单价 <span class="req">*</span></th>
          <template v-if="isDesktop">
            <th class="qt__th-excl">不含税单价</th>
          </template>
          <th class="qt__th-rate">税率</th>
          <template v-if="isDesktop">
            <th class="qt__th-moq">MOQ</th>
          </template>
          <th class="qt__th-lead">交期(天)</th>
          <th class="qt__th-arrival">到货日期</th>
          <template v-if="isDesktop">
            <th class="qt__th-remark">行备注</th>
            <th class="qt__th-attach">行附件</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.lineUid"
          :class="{ 'is-missing': !isRowFilled(row), 'is-readonly': disabled }"
        >
          <!-- 物料（只读，FR-SUP-07） -->
          <td class="qt__td-material">
            <div class="qt__name">
              <span class="qt__seq num">{{ row.seq }}</span>
              <b>{{ row.materialName }}</b>
            </div>
            <div class="qt__spec">
              <span v-if="row.spec">{{ row.spec }} · </span>{{ row.unit || '—' }}
            </div>
            <button
              v-if="!disabled"
              type="button"
              class="qt__tax-switch"
              :class="{ 'is-off': row.taxIncluded === false }"
              role="switch"
              :aria-checked="row.taxIncluded !== false"
              :aria-label="`第 ${row.seq} 行 是否含税报价`"
              @click="patch(row, 'taxIncluded', !row.taxIncluded)"
            >
              <span class="qt__dot" aria-hidden="true" />
              {{ row.taxIncluded === false ? '不含税' : '含税' }}
            </button>
            <span v-else class="qt__tax-ro">{{ row.taxIncluded === false ? '不含税' : '含税' }}</span>
          </td>

          <!-- 需求（只读） -->
          <td class="qt__td-qty num">{{ quantityText(row) }}</td>

          <!-- 含税单价 -->
          <td class="qt__td-price">
            <div class="qt__price-wrap" :class="{ 'is-error': !!priceError(row) }">
              <span class="qt__cur">¥</span>
              <input
                class="qt__input num"
                type="text"
                inputmode="decimal"
                autocomplete="off"
                placeholder="0.00"
                :value="row.priceInclTax"
                :disabled="disabled"
                :aria-label="`第 ${row.seq} 行 ${row.materialName} 含税单价`"
                @input="onPriceInput(row, $event)"
              />
            </div>
            <p v-if="priceError(row)" class="qt__err">{{ priceError(row) }}</p>
          </td>

          <!-- 不含税单价（只读计算） -->
          <td v-if="isDesktop" class="qt__td-excl">
            <input
              class="qt__input qt__input--ro num"
              type="text"
              :value="computePriceExclTax(row)"
              readonly
              tabindex="-1"
              aria-label="不含税单价（自动计算）"
            />
          </td>

          <!-- 税率 -->
          <td class="qt__td-rate">
            <select
              class="qt__input"
              :value="row.taxRate"
              :disabled="disabled"
              :aria-label="`第 ${row.seq} 行 税率`"
              @change="patch(row, 'taxRate', $event.target.value)"
            >
              <option v-for="option in TAX_RATE_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </td>

          <!-- MOQ -->
          <td v-if="isDesktop" class="qt__td-moq">
            <input
              class="qt__input num"
              type="text"
              inputmode="decimal"
              placeholder="默认 1"
              :value="row.moq"
              :disabled="disabled"
              :aria-label="`第 ${row.seq} 行 最小起订量`"
              @input="onMoqInput(row, $event)"
            />
          </td>

          <!-- 交期 -->
          <td class="qt__td-lead">
            <input
              class="qt__input num"
              type="text"
              inputmode="numeric"
              placeholder="如 5"
              :value="row.leadTimeDays"
              :disabled="disabled"
              :aria-label="`第 ${row.seq} 行 交货周期（天）`"
              @input="onLeadInput(row, $event)"
            />
          </td>

          <!-- 到货日期：Q12 定稿原生 date -->
          <td class="qt__td-arrival">
            <input
              class="qt__input"
              type="date"
              :value="row.arrivalDate"
              :min="minDate || undefined"
              :max="maxDate || undefined"
              :disabled="disabled"
              :aria-label="`第 ${row.seq} 行 到货日期`"
              @change="patch(row, 'arrivalDate', $event.target.value)"
            />
          </td>

          <!-- 行备注 -->
          <td v-if="isDesktop" class="qt__td-remark">
            <input
              class="qt__input"
              type="text"
              maxlength="200"
              placeholder="变动或替代方案"
              :value="row.remark"
              :disabled="disabled"
              :aria-label="`第 ${row.seq} 行 行备注`"
              @input="onRemarkInput(row, $event)"
            />
          </td>

          <!-- 行附件 -->
          <td v-if="isDesktop" class="qt__td-attach">
            <AttachmentPicker
              :model-value="row.attachments"
              :disabled="disabled"
              :line-seq="row.seq"
              @update:model-value="patch(row, 'attachments', $event)"
            />
          </td>
        </tr>
        <tr v-if="rows.length === 0">
          <td :colspan="isDesktop ? 10 : 6" class="qt__empty">该询价单没有需要报价的物料</td>
        </tr>
      </tbody>
    </table>
    <p v-for="row in rows.filter((item) => warningsOf(item))" :key="`w-${row.lineUid}`" class="qt__warn">
      第 {{ row.seq }} 行：{{ warningsOf(row) }}
    </p>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.qt-wrap {
  // 宽表在自身内部横向滚动（PRD 10.1），页面整体不横向滚动
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.qt {
  width: 100%;
  min-width: 660px;
  border-collapse: collapse;
  font-size: v.$fs-xs;

  &.is-desktop {
    min-width: 1180px;
  }
}

.qt th {
  padding: 9px 10px;
  font-size: 11.5px;
  font-weight: 600;
  color: v.$ink-500;
  text-align: left;
  white-space: nowrap;
  background: v.$surface-sunken;
  border-bottom: 1px solid v.$line;

  .req {
    color: v.$danger;
  }
}

.qt th.qt__th-qty,
.qt th.qt__th-price,
.qt th.qt__th-excl,
.qt th.qt__th-moq,
.qt th.qt__th-lead {
  text-align: right;
}

.qt td {
  padding: 8px 10px;
  vertical-align: middle;
  border-bottom: 1px solid v.$line-soft;
}

.qt tr.is-missing {
  background: #fffcfb;

  .qt__name b {
    color: v.$danger;
  }
}

.qt tr.is-readonly td {
  color: v.$ink-500;
}

.qt__td-material {
  min-width: 190px;
}

.qt__name {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.qt__seq {
  flex: none;
  min-width: 14px;
  font-size: 11px;
  color: v.$ink-400;
}

.qt__name b {
  font-size: v.$fs-sm;
  font-weight: 600;
  color: v.$ink-900;
}

.qt__spec {
  margin-top: 2px;
  font-size: 11px;
  color: v.$ink-400;
}

.qt__tax-switch {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 26px;
  margin-top: 4px;
  padding: 0 8px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  color: v.$brand-700;
  background: v.$brand-50;
  border: 1px solid v.$brand-100;
  border-radius: 100px;
  cursor: pointer;

  &.is-off {
    color: v.$warn;
    background: v.$warn-bg;
    border-color: v.$warn-line;
  }
}

.qt__dot {
  width: 6px;
  height: 6px;
  background: currentColor;
  border-radius: 50%;
}

.qt__tax-ro {
  display: inline-block;
  margin-top: 4px;
  font-size: 11px;
  color: v.$ink-400;
}

.qt__td-qty {
  width: 90px;
  font-family: v.$font-num;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}

.qt__td-price {
  width: 150px;
}

.qt__price-wrap {
  display: flex;
  align-items: center;
  overflow: hidden;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;

  &:focus-within {
    border-color: v.$brand-600;
    box-shadow: 0 0 0 3px v.$brand-100;
  }

  &.is-error {
    border-color: v.$danger-line;
  }
}

.qt__cur {
  flex: none;
  padding-left: 8px;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

// 输入框字号：平板 16px（防 iOS 聚焦放大），桌面 14px
.qt__input {
  width: 100%;
  min-height: 34px;
  padding: 0 8px;
  font-family: inherit;
  font-size: 16px;
  color: v.$ink-900;
  text-align: left;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;

  &:focus {
    border-color: v.$brand-600;
    outline: none;
    box-shadow: 0 0 0 3px v.$brand-100;
  }

  &:disabled {
    color: v.$ink-500;
    background: v.$surface-sunken;
    -webkit-text-fill-color: v.$ink-500;
    opacity: 1;
  }
}

.qt__price-wrap .qt__input {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  text-align: right;
}

.qt__input.num {
  font-family: v.$font-num;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.qt__input--ro {
  color: v.$ink-500;
  background: v.$surface-sunken;
  -webkit-text-fill-color: v.$ink-500;
}

.qt__td-excl,
.qt__td-moq {
  width: 110px;
}

.qt__td-rate {
  width: 96px;
}

.qt__td-lead {
  width: 92px;
}

.qt__td-arrival {
  width: 148px;
}

.qt__td-remark {
  width: 200px;
}

.qt__td-attach {
  width: 210px;
  padding-bottom: 24px;
}

.qt__err {
  margin: 4px 0 0;
  font-size: 11px;
  color: v.$danger;
}

.qt__empty {
  padding: 22px 10px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
  text-align: center;
}

.qt__warn {
  margin: 0;
  padding: 6px 10px;
  font-size: 11.5px;
  color: v.$warn;
  background: v.$warn-bg;
}

@include bp.desktop-up {
  .qt__input {
    font-size: 14px;
  }
}
</style>
