<script setup>
/**
 * MaterialCard — 手机端物料卡片（设计稿 03-pages-supplier.html 的 .mat / FR-RWD-17）
 * ---------------------------------------------------------------------------
 * 结构严格对齐设计稿与 PRD 10.3：
 *   顶部：序号 + 材料名称 + 已填/未填角标；次行：规格 · 单位 · 采购数量（**只读**）
 *   中部：含税单价（唯一默认展开项，占满宽度、44px 高、18px 字号、inputmode=decimal）
 *   折叠：是否含税 / 税率 / 不含税单价（只读）/ MOQ / 交货周期 / 到货日期(原生 date) / 行备注 / 行附件
 * 已填 → 卡片绿边；段内未填 → 红边并写出「未填写」（设计稿 B 屏）。
 * 所有输入框字号 ≥16px（防 iOS 聚焦放大，FR-RWD-08）。
 */
import { computed, ref } from 'vue'

import { TAX_RATE_OPTIONS, computePriceExclTax, extraFilledCount, isRowFilled, rowWarnings, sanitizeDecimal3, sanitizeInt, sanitizePrice, validatePrice } from '../quoteModel'
import AttachmentPicker from './AttachmentPicker.vue'

defineOptions({ name: 'MaterialCard' })

const props = defineProps({
  row: { type: Object, required: true },
  /** 只读（截止后） */
  disabled: { type: Boolean, default: false },
  /** 段内未填高亮 */
  highlightMissing: { type: Boolean, default: false },
  /** 原生 date 控件取值范围（不得早于今天 / 不晚于截止+1年） */
  minDate: { type: String, default: '' },
  maxDate: { type: String, default: '' },
})

const emit = defineEmits(['patch'])

const open = ref(false)
const touched = ref(false)

const filled = computed(() => isRowFilled(props.row))
const priceState = computed(() => validatePrice(props.row.priceInclTax))
const priceError = computed(() => (touched.value && !priceState.value.ok ? priceState.value.message : ''))
const extraCount = computed(() => extraFilledCount(props.row))
const warnings = computed(() => rowWarnings(props.row))
const exclTax = computed(() => computePriceExclTax(props.row))
const seqText = computed(() => String(props.row.seq || 0).padStart(2, '0'))
const quantityText = computed(() => {
  const raw = String(props.row.quantity ?? '').trim()
  if (!raw) return '—'
  const n = Number(raw)
  if (!Number.isFinite(n)) return raw
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 }).format(n)
})
const moqHint = computed(() => {
  const qty = Number(String(props.row.quantity ?? '').trim())
  const moq = Number(String(props.row.moq ?? '').trim())
  if (!Number.isFinite(qty)) return ''
  if (Number.isFinite(moq) && moq > 0) {
    return moq > qty
      ? `采购数量 ${quantityText.value}，低于 MOQ，请确认可满足`
      : `采购数量 ${quantityText.value}，MOQ ${props.row.moq} 满足起订`
  }
  return `采购数量 ${quantityText.value}`
})

function patch(key, value) {
  emit('patch', { [key]: value })
}

function onPriceInput(event) {
  patch('priceInclTax', sanitizePrice(event.target.value))
}

function onMoqInput(event) {
  patch('moq', sanitizeDecimal3(event.target.value))
}

function onLeadInput(event) {
  patch('leadTimeDays', sanitizeInt(event.target.value))
}

function onRemarkInput(event) {
  patch('remark', String(event.target.value || '').slice(0, 200))
}

function toggleTax() {
  if (props.disabled) return
  patch('taxIncluded', !props.row.taxIncluded)
}
</script>

<template>
  <article
    class="mat"
    :class="{ 'is-filled': filled, 'is-missing': highlightMissing && !filled, 'is-readonly': disabled }"
  >
    <header class="mat__head">
      <div class="mat__l1">
        <span class="mat__seq">{{ seqText }}</span>
        <span class="mat__name">{{ row.materialName }}</span>
        <span v-if="!disabled" class="mat__flag" :class="filled ? 'is-ok' : 'is-no'">
          {{ filled ? '已填' : '未填' }}
        </span>
      </div>
      <div class="mat__l2">
        <span v-if="row.spec">{{ row.spec }}</span>
        <em v-if="row.spec">·</em>
        <span>单位 {{ row.unit || '—' }}</span>
        <em>·</em>
        <span>采购 {{ quantityText }}</span>
      </div>
    </header>

    <div class="mat__price">
      <label class="mat__label" :for="`price-${row.lineUid}`">
        含税单价 <span class="req">*</span>
        <span v-if="!disabled && highlightMissing && !filled" class="miss">未填写</span>
      </label>
      <div class="mat__input-wrap">
        <span class="mat__cur">¥</span>
        <input
          :id="`price-${row.lineUid}`"
          class="mat__input num"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          :value="row.priceInclTax"
          :disabled="disabled"
          :aria-label="`第 ${row.seq} 行 ${row.materialName} 含税单价`"
          :aria-invalid="priceError ? 'true' : 'false'"
          placeholder="0.00"
          @input="onPriceInput"
          @focus="touched = true"
        />
        <span class="mat__unit">元/{{ row.unit || '单位' }}</span>
      </div>
      <p v-if="priceError" class="mat__err">{{ priceError }}</p>
    </div>

    <button type="button" class="mat__toggle" :aria-expanded="open" @click="open = !open">
      <span>{{ open ? '收起更多报价信息' : '更多报价信息（税率 / MOQ / 交期 / 到货 / 备注）' }}</span>
      <span class="mat__toggle-c">
        {{ open ? '⌃' : extraCount ? `${extraCount} 项已填 ›` : '›' }}
      </span>
    </button>

    <div v-if="open" class="mat__more">
      <div class="frow">
        <span class="frow__label">是否含税</span>
        <div class="frow__ctl is-inline">
          <button
            type="button"
            class="sw"
            :class="{ 'is-off': row.taxIncluded === false }"
            :disabled="disabled"
            role="switch"
            :aria-checked="row.taxIncluded !== false"
            :aria-label="`第 ${row.seq} 行 是否含税`"
            @click="toggleTax"
          >
            <i aria-hidden="true" />
          </button>
          <span class="sw__text">{{ row.taxIncluded === false ? '不含税报价' : '含税报价' }}</span>
        </div>
      </div>

      <div class="frow">
        <label class="frow__label" :for="`tax-${row.lineUid}`">税率</label>
        <div class="frow__ctl">
          <select
            :id="`tax-${row.lineUid}`"
            class="inp"
            :value="row.taxRate"
            :disabled="disabled"
            :aria-label="`第 ${row.seq} 行 税率`"
            @change="patch('taxRate', $event.target.value)"
          >
            <option v-for="option in TAX_RATE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p v-if="row.taxIncluded === false" class="hint">含税开关为「否」时必须选择税率</p>
        </div>
      </div>

      <div class="frow">
        <span class="frow__label">不含税单价</span>
        <div class="frow__ctl">
          <input class="inp num is-ro" type="text" :value="exclTax" readonly tabindex="-1" aria-label="不含税单价（自动计算）" />
        </div>
      </div>

      <div class="frow">
        <label class="frow__label" :for="`moq-${row.lineUid}`">最小起订量</label>
        <div class="frow__ctl">
          <input
            :id="`moq-${row.lineUid}`"
            class="inp num"
            type="text"
            inputmode="decimal"
            placeholder="默认 1"
            :value="row.moq"
            :disabled="disabled"
            @input="onMoqInput"
          />
          <p class="hint">{{ moqHint }}</p>
        </div>
      </div>

      <div class="frow">
        <label class="frow__label" :for="`lead-${row.lineUid}`">交货周期</label>
        <div class="frow__ctl">
          <input
            :id="`lead-${row.lineUid}`"
            class="inp num"
            type="text"
            inputmode="numeric"
            placeholder="如 5"
            :value="row.leadTimeDays"
            :disabled="disabled"
            @input="onLeadInput"
          />
          <p class="hint">单位：天（与到货日期至少填一项）</p>
        </div>
      </div>

      <!-- 到货日期：Q12 定稿用原生 date 控件（PRD 10.3 第 10 条） -->
      <div class="frow">
        <label class="frow__label" :for="`arrival-${row.lineUid}`">到货日期</label>
        <div class="frow__ctl">
          <input
            :id="`arrival-${row.lineUid}`"
            class="inp"
            type="date"
            :value="row.arrivalDate"
            :min="minDate || undefined"
            :max="maxDate || undefined"
            :disabled="disabled"
            @change="patch('arrivalDate', $event.target.value)"
          />
        </div>
      </div>

      <div class="frow is-top">
        <label class="frow__label" :for="`remark-${row.lineUid}`">行备注</label>
        <div class="frow__ctl">
          <textarea
            :id="`remark-${row.lineUid}`"
            class="inp is-area"
            rows="2"
            maxlength="200"
            placeholder="填写变动或替代方案"
            :value="row.remark"
            :disabled="disabled"
            @input="onRemarkInput"
          />
        </div>
      </div>

      <div class="frow is-top">
        <span class="frow__label">行附件</span>
        <div class="frow__ctl">
          <AttachmentPicker
            :model-value="row.attachments"
            :disabled="disabled"
            :line-seq="row.seq"
            @update:model-value="patch('attachments', $event)"
          />
        </div>
      </div>
    </div>

    <p v-for="warning in warnings" :key="warning" class="mat__warn">{{ warning }}</p>
  </article>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.mat {
  position: relative;
  margin-bottom: 10px;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;

  &.is-filled {
    border-color: v.$ok-line;
  }

  &.is-missing {
    background: #fffcfb;
    border-color: v.$danger-line;

    .mat__seq,
    .mat__name,
    .mat__label {
      color: v.$danger;
    }
  }
}

.mat__head {
  padding: 11px v.$sp-3 9px;
}

.mat__l1 {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-2;
}

.mat__seq {
  flex: none;
  min-width: 17px;
  padding-top: 2px;
  font-family: v.$font-num;
  font-size: 11px;
  font-weight: 700;
  color: v.$ink-400;
}

.mat__name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.mat__flag {
  flex: none;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid;
  border-radius: 100px;

  &.is-ok {
    color: v.$ok;
    background: v.$ok-bg;
    border-color: v.$ok-line;
  }

  &.is-no {
    color: v.$ink-400;
    background: v.$surface-sunken;
    border-color: v.$line;
  }
}

.mat__l2 {
  display: flex;
  flex-wrap: wrap;
  gap: v.$sp-2;
  margin: 4px 0 0 25px;
  font-size: 11.5px;
  color: v.$ink-500;

  em {
    font-style: normal;
    color: v.$ink-400;
  }
}

.mat__price {
  padding: 0 v.$sp-3 11px;
}

.mat__label {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: v.$ink-700;

  .req {
    color: v.$danger;
  }

  .miss {
    color: v.$danger;
  }
}

.mat__input-wrap {
  display: flex;
  align-items: center;
  overflow: hidden;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;

  &:focus-within {
    border-color: v.$brand-600;
    box-shadow: 0 0 0 3px v.$brand-100;
  }
}

.mat.is-filled .mat__input-wrap {
  background: #fbfefc;
  border-color: v.$ok-line;
}

.mat.is-missing .mat__input-wrap {
  border-color: v.$danger-line;
}

.mat.is-readonly .mat__input-wrap {
  background: v.$surface-sunken;
  border-color: v.$line;
}

.mat__cur {
  flex: none;
  padding: 0 9px 0 11px;
  font-size: 14px;
  font-weight: 600;
  color: v.$ink-400;
}

// 单价：44px 高 / 18px 字号 / inputmode=decimal（FR-RWD-18）
.mat__input {
  flex: 1;
  min-width: 0;
  height: 44px;
  font-family: v.$font-num;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: v.$ink-900;
  background: transparent;
  border: 0;
  outline: none;

  &::placeholder {
    font-weight: 500;
    color: v.$ink-300;
  }

  &:disabled {
    color: v.$ink-700;
    -webkit-text-fill-color: v.$ink-700;
    opacity: 1;
  }
}

.mat__unit {
  display: flex;
  align-items: center;
  flex: none;
  height: 44px;
  padding: 0 11px;
  font-size: v.$fs-xs;
  color: v.$ink-400;
  border-left: 1px solid v.$line-soft;
}

.mat__err {
  margin: 5px 0 0;
  font-size: 11.5px;
  color: v.$danger;
}

.mat__toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 38px;
  padding: 9px v.$sp-3;
  font-family: inherit;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$brand-700;
  text-align: left;
  background: #fcfdfd;
  border: 0;
  border-top: 1px dashed v.$line;
  cursor: pointer;

  &[aria-expanded='true'] {
    color: v.$brand-800;
    background: v.$brand-50;
    border-top-color: v.$brand-100;
  }
}

.mat__toggle-c {
  margin-left: auto;
  font-weight: 500;
  color: v.$ink-400;
}

.mat__more {
  padding: 11px v.$sp-3;
  background: #fcfdfd;
  border-top: 1px solid v.$line-soft;
}

.frow {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;

  &.is-top {
    align-items: flex-start;
  }

  &:last-child {
    margin-bottom: 0;
  }
}

.frow__label {
  flex: none;
  width: 82px;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-700;

  .frow.is-top & {
    padding-top: 9px;
  }
}

.frow__ctl {
  flex: 1;
  min-width: 0;
}

.sw {
  position: relative;
  flex: none;
  width: 44px;
  height: 25px;
  background: v.$brand-600;
  border: 0;
  border-radius: 100px;
  cursor: pointer;

  i {
    position: absolute;
    top: 2.5px;
    right: 2.5px;
    width: 20px;
    height: 20px;
    background: #fff;
    border-radius: 50%;
    box-shadow: v.$sh-1;
  }

  &.is-off {
    background: v.$line-strong;

    i {
      right: auto;
      left: 2.5px;
    }
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.7;
  }
}

.sw__text {
  font-size: v.$fs-xs;
  color: v.$ink-700;
}

.frow:not(.is-top) .frow__ctl {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.frow__ctl.is-inline {
  flex-direction: row;
  align-items: center;
  gap: 9px;
}

// 折叠区输入框：字号 16px（≥16px 防 iOS 放大）
.inp {
  width: 100%;
  min-height: 40px;
  padding: 0 10px;
  font-family: inherit;
  font-size: 16px;
  color: v.$ink-900;
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

.inp.num {
  font-family: v.$font-num;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.inp.is-ro {
  color: v.$ink-500;
  background: v.$surface-sunken;
  -webkit-text-fill-color: v.$ink-500;
  text-align: right;
}

.inp.is-area {
  min-height: 62px;
  padding: 9px 10px;
  line-height: 1.5;
  resize: none;
}

select.inp {
  appearance: none;
  padding-right: 28px;
  background-image: linear-gradient(45deg, transparent 50%, v.$ink-400 50%),
    linear-gradient(135deg, v.$ink-400 50%, transparent 50%);
  background-repeat: no-repeat;
  background-position: calc(100% - 16px) 17px, calc(100% - 11px) 17px;
  background-size: 5px 5px, 5px 5px;
}

.hint {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: v.$ink-400;
}

.mat__warn {
  margin: 0;
  padding: 8px v.$sp-3 10px;
  font-size: 11.5px;
  color: v.$warn;
  background: v.$warn-bg;
  border-top: 1px dashed v.$warn-line;
}
</style>
