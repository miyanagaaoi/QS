<script setup>
/**
 * SubmitConfirmSheet — 提交前确认（设计稿 03-4 C 屏 / FR-RWD-20 / PRD 10.4）
 * ---------------------------------------------------------------------------
 * 两种形态：
 *  1. 有漏填 → 列出**未填行号 + 物料**，**阻断提交**（不渲染"确认提交"按钮），
 *     给出「跳到第 N 行继续填写」「先保存草稿」「取消」。
 *  2. 已填全 → 提示「提交后截止前仍可修改」+ 本次提交摘要，按钮「确认提交」。
 * 手机端按钮纵向排列，"取消"在最下方易达位；打开时锁定 body 滚动（FR-RWD-02）。
 */
import { computed } from 'vue'

import { useBodyScrollLock } from '@/composables/useBodyScrollLock'

import { computePriceExclTax, isRowFilled, sumFilled } from '../quoteModel'

defineOptions({ name: 'SubmitConfirmSheet' })

const props = defineProps({
  visible: { type: Boolean, default: false },
  /** 整单所有行 */
  rows: { type: Array, default: () => [] },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['jump', 'save-draft', 'cancel', 'confirm'])

useBodyScrollLock(computed(() => props.visible))

const missingRows = computed(() => props.rows.filter((row) => !isRowFilled(row)))
const stats = computed(() => sumFilled(props.rows))

/** 含税合计：仅统计「含税」行，避免与不含税行混算（口径写在界面上） */
const summary = computed(() => {
  let amount = 0
  let amountLines = 0
  let leadSum = 0
  let leadCount = 0
  props.rows.forEach((row) => {
    if (!isRowFilled(row)) return
    const price = row.taxIncluded === false
      ? Number(computePriceExclTax(row))
      : Number(String(row.priceInclTax ?? '').trim())
    const qty = Number(String(row.quantity ?? '').trim())
    if (Number.isFinite(price) && Number.isFinite(qty)) {
      amount += price * qty
      amountLines += 1
    }
    const lead = Number(String(row.leadTimeDays ?? '').trim())
    if (Number.isFinite(lead) && lead > 0) {
      leadSum += lead
      leadCount += 1
    }
  })
  return {
    amount,
    amountLines,
    taxMix: props.rows.some((row) => isRowFilled(row) && row.taxIncluded === false),
    avgLead: leadCount ? Math.round(leadSum / leadCount) : null,
  }
})

const amountText = computed(() =>
  summary.value.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
)

function jumpToFirstMissing() {
  const first = missingRows.value[0]
  if (first) emit('jump', first.seq)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div v-if="visible" class="sheet-mask" @click.self="emit('cancel')">
        <section class="sheet" role="dialog" aria-modal="true" :aria-label="missingRows.length ? '还有未填写行' : '确认提交报价'">
          <div class="sheet__grip" aria-hidden="true" />

          <template v-if="missingRows.length">
            <h2 class="sheet__title">还有 {{ missingRows.length }} 行未填写单价</h2>
            <p class="sheet__sub">提交前需要补齐所有物料的价格</p>

            <div class="sheet__items">
              <div v-for="row in missingRows" :key="row.lineUid" class="sheet__item">
                <span class="sheet__item-no num">第 {{ row.seq }} 行</span>
                <span class="sheet__item-text">
                  {{ row.materialName }}
                  <em v-if="row.spec"> · {{ row.spec }}</em>
                  <em> · {{ row.unit || '—' }} · 采购 {{ row.quantity }}</em>
                </span>
              </div>
            </div>

            <p class="sheet__hint">提示：可直接跳到未填行继续填写，已填内容不会丢失。</p>

            <div class="sheet__acts">
              <button type="button" class="btn btn-primary btn-lg" @click="jumpToFirstMissing">
                跳到第 {{ missingRows[0].seq }} 行继续填写
              </button>
              <button type="button" class="btn btn-secondary btn-lg" @click="emit('save-draft')">
                先保存草稿
              </button>
              <button type="button" class="btn btn-ghost btn-lg" @click="emit('cancel')">取消</button>
            </div>
          </template>

          <template v-else>
            <h2 class="sheet__title">确认提交报价？</h2>
            <p class="sheet__sub">
              共 {{ stats.total }} 行已全部填写，提交后<b>截止前仍可修改</b>
            </p>

            <div class="sheet__kv">
              <div class="sheet__row">
                <span>已报价行数</span><b class="num">{{ stats.filled }} / {{ stats.total }} 行</b>
              </div>
              <div class="sheet__row">
                <span>报价金额合计{{ summary.taxMix ? '（含税行口径）' : '（含税）' }}</span>
                <b class="num">¥{{ amountText }}</b>
              </div>
              <div class="sheet__row">
                <span>平均交货周期</span>
                <b class="num">{{ summary.avgLead === null ? '—' : `${summary.avgLead} 天` }}</b>
              </div>
            </div>

            <div class="sheet__note">
              提交后可在截止时间前随时返回修改，系统会保留每次改价记录。
            </div>

            <div class="sheet__acts">
              <button
                type="button"
                class="btn btn-primary btn-lg"
                :disabled="submitting"
                @click="emit('confirm')"
              >
                {{ submitting ? '提交中…' : '确认提交' }}
              </button>
              <button type="button" class="btn btn-ghost btn-lg" @click="emit('cancel')">取消</button>
            </div>
          </template>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.sheet-mask {
  position: fixed;
  inset: 0;
  z-index: v.$z-drawer;
  display: flex;
  align-items: flex-end;
  background: rgba(15, 20, 25, 0.42);
}

.sheet {
  width: 100%;
  max-height: 82vh;
  overflow-y: auto;
  padding: 8px v.$sp-3 calc(14px + env(safe-area-inset-bottom, 0px));
  background: v.$surface;
  border-radius: 14px 14px 0 0;
  box-shadow: v.$sh-3;
}

.sheet__grip {
  width: 40px;
  height: 4px;
  margin: 0 auto 12px;
  background: v.$line-strong;
  border-radius: 100px;
}

.sheet__title {
  font-size: v.$fs-lg;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: v.$ink-900;
}

.sheet__sub {
  margin: 4px 0 12px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.sheet__items {
  padding: 10px;
  margin-bottom: 12px;
  font-size: v.$fs-xs;
  background: v.$surface-sunken;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.sheet__item {
  display: flex;
  gap: v.$sp-2;
  align-items: baseline;
  padding: 4px 0;
}

.sheet__item-no {
  flex: none;
  font-weight: 700;
  color: v.$danger;
}

.sheet__item-text {
  color: v.$ink-700;
  overflow-wrap: anywhere;

  em {
    font-style: normal;
    color: v.$ink-500;
  }
}

.sheet__hint {
  margin: 0 0 12px;
  font-size: 11.5px;
  color: v.$ink-400;
}

.sheet__kv {
  padding: 4px 10px;
  margin-bottom: 12px;
  background: v.$surface-sunken;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.sheet__row {
  display: flex;
  justify-content: space-between;
  gap: v.$sp-3;
  padding: 7px 0;
  font-size: v.$fs-xs;
  color: v.$ink-500;
  border-bottom: 1px dashed v.$line;

  &:last-child {
    border-bottom: 0;
  }

  b {
    color: v.$ink-900;
  }
}

.sheet__note {
  padding: 10px v.$sp-3;
  font-size: 11.5px;
  line-height: 1.5;
  color: #154882;
  background: v.$info-bg;
  border: 1px solid v.$info-line;
  border-radius: v.$r-md;
}

.sheet__acts {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
  margin-top: 14px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: v.$touch-target;
  padding: 0 14px;
  font-family: inherit;
  font-size: v.$fs-body;
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: v.$r-md;
  cursor: pointer;
}

.btn-lg {
  min-height: 46px;
  font-size: v.$fs-body;
}

.btn-primary {
  color: #fff;
  background: v.$brand-700;
  border-color: v.$brand-700;

  &:disabled {
    color: v.$ink-300;
    background: v.$surface-sunken;
    border-color: v.$line;
    cursor: not-allowed;
  }
}

.btn-secondary {
  color: v.$ink-700;
  background: v.$surface;
  border-color: v.$line-strong;
}

.btn-ghost {
  color: v.$brand-700;
  background: transparent;
}

.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.2s ease;
}

.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

@include bp.tablet-up {
  .sheet-mask {
    align-items: center;
    justify-content: center;
    padding: v.$sp-5;
  }

  .sheet {
    max-width: 520px;
    border-radius: v.$r-lg;
  }

  .sheet__grip {
    display: none;
  }

  // 大屏按钮横向排列更省空间（"取消"仍在右下方易达位）
  .sheet__acts {
    flex-direction: row-reverse;
    justify-content: flex-start;
  }
}
</style>
