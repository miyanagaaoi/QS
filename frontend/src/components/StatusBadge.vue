<script setup>
/**
 * StatusBadge — 状态徽标（圆点 + 文字）
 * ---------------------------------------------------------------------------
 * 设计约束（设计系统 02 节）：
 *  1. **必须带文字**，颜色只是加速扫读，不是唯一区分手段；
 *  2. 语义色只能取自设计令牌（草稿/待报价=灰、已发布=蓝、报价中/已截止=琥珀、
 *     已报价=绿、最低价=琥珀底、未报价/停用=红）。
 *
 * 用法：
 *   <StatusBadge status="published" />
 *   <StatusBadge status="partial" :filled="3" :total="8" />   → 报价中 3/8
 *   <StatusBadge status="best" />                              → 最低价
 *   <StatusBadge tone="danger" label="未报价" />                → 自定义
 */
import { computed } from 'vue'

import { TONE_CLASS, assignProgressText, statusMeta } from './status'

defineOptions({ name: 'StatusBadge' })

const props = defineProps({
  /** 后端状态字面量：draft/published/closed/pending/partial/quoted/best/... */
  status: { type: String, default: '' },
  /** 覆盖文案；未传时按 status 查表，查不到则原样显示 status */
  label: { type: String, default: '' },
  /** 覆盖语义色：muted | info | warn | ok | danger | best | brand */
  tone: { type: String, default: '' },
  /** 已填行数 / 总行数（配合 status=partial|quoted 显示「报价中 3/8」） */
  filled: { type: [Number, String], default: null },
  total: { type: [Number, String], default: null },
  /** 圆点（仅装饰，不承担唯一区分职责） */
  dot: { type: Boolean, default: true },
  /** small | default */
  size: { type: String, default: 'default' },
})

const meta = computed(() => statusMeta(props.status))

const text = computed(() => {
  if (props.label) return props.label
  const filled = props.filled === null ? NaN : Number(props.filled)
  const total = props.total === null ? NaN : Number(props.total)
  if (Number.isFinite(filled) && Number.isFinite(total)) {
    return assignProgressText(props.status, filled, total)
  }
  return meta.value.label
})

const toneClass = computed(() => TONE_CLASS[props.tone || meta.value.tone] || TONE_CLASS.muted)
</script>

<template>
  <span class="status-badge" :class="[toneClass, size === 'small' ? 'is-small' : '']">
    <span v-if="dot" class="status-badge__dot" aria-hidden="true" />
    <span class="status-badge__text">{{ text }}</span>
  </span>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

// 圆点 + 文字 + 1px 描边（设计稿 .badge）
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 9px;
  border: 1px solid;
  border-radius: 100px;
  font-size: v.$fs-xs;
  font-weight: 600;
  line-height: 1.75;
  white-space: nowrap;

  &.is-small {
    font-size: 11px;
    padding: 0 7px;
  }
}

.status-badge__dot {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.is-muted {
  color: v.$muted;
  background: v.$muted-bg;
  border-color: v.$muted-line;
}

.is-info {
  color: v.$info;
  background: v.$info-bg;
  border-color: v.$info-line;
}

.is-warn {
  color: v.$warn;
  background: v.$warn-bg;
  border-color: v.$warn-line;
}

.is-ok {
  color: v.$ok;
  background: v.$ok-bg;
  border-color: v.$ok-line;
}

.is-danger {
  color: v.$danger;
  background: v.$danger-bg;
  border-color: v.$danger-line;
}

.is-best {
  color: v.$best-ink;
  background: v.$best-bg;
  border-color: v.$best-line;
}

.is-brand {
  color: v.$brand-800;
  background: v.$brand-50;
  border-color: v.$brand-100;
}
</style>
