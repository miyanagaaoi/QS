<script setup>
/**
 * PmGantt — 多项目进度甘特图（CH-009，看板内嵌、可折叠、**只读**）
 * ---------------------------------------------------------------------------
 * 数据来源：看板接口 `GET /api/pm/board` 的项目列表（开工日期 / 计划竣工 /
 * 总体进度 / 状态），不额外请求接口。
 *
 * 横轴：以所有项目的「最早开工」到「最晚计划竣工」为范围，按**月份**刻度；
 * 跨度超过 24 个月自动改**季度**刻度，避免刻度挤成一团。
 *
 * 交互：只读（不改日期）。悬停看起止日期与进度；点击行跳到该项目工期计划表。
 * 移动端：左侧项目名列固定，右侧时间轴横向滚动。
 */
import { computed } from 'vue'

const props = defineProps({
  projects: { type: Array, default: () => [] },
})

const emit = defineEmits(['open'])

const DAY = 24 * 60 * 60 * 1000

function parseDate(value) {
  if (!value) return null
  const [y, m, d] = String(value).split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(Date.UTC(y, m - 1, d))
}

const dated = computed(() =>
  props.projects
    .map((p) => ({ ...p, start: parseDate(p.start_date), end: parseDate(p.plan_end_date) }))
    .filter((p) => p.start && p.end && p.end >= p.start),
)

/** 时间轴范围：两端各留半个月，并对齐到月初/月末 */
const range = computed(() => {
  if (!dated.value.length) return null
  const starts = dated.value.map((p) => p.start.getTime())
  const ends = dated.value.map((p) => p.end.getTime())
  const minRaw = new Date(Math.min(...starts))
  const maxRaw = new Date(Math.max(...ends))
  const min = new Date(Date.UTC(minRaw.getUTCFullYear(), minRaw.getUTCMonth(), 1))
  const max = new Date(Date.UTC(maxRaw.getUTCFullYear(), maxRaw.getUTCMonth() + 1, 0))
  const totalDays = Math.max(1, (max.getTime() - min.getTime()) / DAY)
  return { min, max, totalDays }
})

/** 刻度：跨度 ≤24 个月按月，否则按季度 */
const ticks = computed(() => {
  if (!range.value) return []
  const { min, max, totalDays } = range.value
  const months = (max.getUTCFullYear() - min.getUTCFullYear()) * 12 + (max.getUTCMonth() - min.getUTCMonth()) + 1
  const byQuarter = months > 24
  const step = byQuarter ? 3 : 1
  const out = []
  let cursor = new Date(Date.UTC(min.getUTCFullYear(), min.getUTCMonth(), 1))
  while (cursor <= max) {
    const left = ((cursor.getTime() - min.getTime()) / DAY / totalDays) * 100
    out.push({
      key: cursor.toISOString().slice(0, 7),
      left,
      label: byQuarter
        ? `Q${Math.floor(cursor.getUTCMonth() / 3) + 1} ${String(cursor.getUTCFullYear()).slice(2)}`
        : `${String(cursor.getUTCMonth() + 1)}月`,
      sub: byQuarter ? String(cursor.getUTCFullYear()) : String(cursor.getUTCFullYear()).slice(2),
      yearStart: cursor.getUTCMonth() === 0,
    })
    cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + step, 1))
  }
  return out
})

const todayLeft = computed(() => {
  if (!range.value) return null
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  const left = ((today - range.value.min.getTime()) / DAY / range.value.totalDays) * 100
  if (left < 0 || left > 100) return null
  return left
})

const rows = computed(() => {
  if (!range.value) return []
  const { min, totalDays } = range.value
  return dated.value.map((p) => {
    const offsetDays = (p.start.getTime() - min.getTime()) / DAY
    const spanDays = (p.end.getTime() - p.start.getTime()) / DAY
    const color = p.overdue ? 'danger' : p.status === 'done' ? 'ok' : p.status === 'paused' ? 'warn' : 'brand'
    return {
      id: p.id,
      name: p.name,
      status: p.status,
      color,
      left: (offsetDays / totalDays) * 100,
      width: Math.max(0.8, (spanDays / totalDays) * 100),
      progress: Math.max(0, Math.min(100, p.progress ?? 0)),
      startText: p.start_date,
      endText: p.plan_end_date,
      stage: p.current_stage || '未设置',
      stageIndex: p.stage_index ?? 0,
      stageTotal: p.stage_total ?? 0,
      remaining: p.remaining_days,
      processDone: p.process_done ?? 0,
      processTotal: p.process_total ?? 0,
    }
  })
})
</script>

<template>
  <div class="gantt">
    <div v-if="!rows.length" class="gantt__empty">
      还没有同时设置了「开工日期」和「计划竣工日期」的项目，无法绘制甘特图
    </div>

    <div v-else class="gantt__scroll">
      <div class="gantt__inner">
        <!-- 表头刻度 -->
        <div class="gantt__head">
          <div class="gantt__head-label">项目</div>
          <div class="gantt__head-track">
            <div
              v-for="tick in ticks"
              :key="tick.key"
              class="gantt__tick"
              :class="{ 'is-year': tick.yearStart }"
              :style="{ left: `${tick.left}%` }"
            >
              <span class="gantt__tick-label">{{ tick.label }}</span>
              <span class="gantt__tick-sub">{{ tick.sub }}</span>
            </div>
            <div v-if="todayLeft !== null" class="gantt__today-head" :style="{ left: `${todayLeft}%` }">
              <span class="gantt__today-tag">今天</span>
            </div>
          </div>
        </div>

        <!-- 行 -->
        <div class="gantt__body">
          <div v-for="row in rows" :key="row.id" class="gantt__row">
            <button class="gantt__label" type="button" :title="`${row.name}（点击查看工期计划表）`" @click="emit('open', row.id)">
              {{ row.name }}
            </button>
            <div class="gantt__track">
              <div
                v-for="tick in ticks"
                :key="tick.key"
                class="gantt__grid"
                :class="{ 'is-year': tick.yearStart }"
                :style="{ left: `${tick.left}%` }"
              />
              <span
                v-if="todayLeft !== null"
                class="gantt__today-line"
                :style="{ left: `${todayLeft}%` }"
              />
              <el-tooltip placement="top" :show-after="80">
                <template #content>
                  <div class="gantt__tip">
                    <b>{{ row.name }}</b>
                    <div>开工 → 计划竣工：{{ row.startText }} → {{ row.endText }}</div>
                    <div>
                      当前阶段：{{ row.stage }}
                      <template v-if="row.stageTotal">（{{ row.stageIndex }}/{{ row.stageTotal }}）</template>
                    </div>
                    <div>阶段进度：{{ row.progress }}%（按当前阶段计算）</div>
                    <div>工序完成：{{ row.processDone }}/{{ row.processTotal }}</div>
                    <div v-if="row.remaining !== null">
                      {{ row.remaining < 0 ? `已超期 ${Math.abs(row.remaining)} 天` : `剩余 ${row.remaining} 天` }}
                    </div>
                  </div>
                </template>
                <button
                  type="button"
                  :class="['gantt__bar', `gantt__bar--${row.color}`]"
                  :style="{ left: `${row.left}%`, width: `${row.width}%` }"
                  @click="emit('open', row.id)"
                >
                  <span class="gantt__bar-fill" :style="{ width: `${row.progress}%` }" />
                  <span class="gantt__bar-text">{{ row.progress }}%</span>
                </button>
              </el-tooltip>
            </div>
          </div>
        </div>

      </div>
    </div>

    <div class="gantt__legend">
      <span class="gantt__legend-item"><i class="dot dot--brand" />进行中</span>
      <span class="gantt__legend-item"><i class="dot dot--ok" />已竣工</span>
      <span class="gantt__legend-item"><i class="dot dot--warn" />暂停</span>
      <span class="gantt__legend-item"><i class="dot dot--danger" />已超期</span>
      <span class="gantt__legend-hint">横轴为日期；条内深色部分为「按当前阶段」算出的整体进度；点击条形可进入工期计划表</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.gantt {
  --gantt-label: 168px;
}

.gantt__empty {
  padding: v.$sp-4;
  font-size: v.$fs-sm;
  color: v.$ink-400;
  text-align: center;
}

.gantt__scroll {
  overflow-x: auto;
}

.gantt__inner {
  position: relative;
  min-width: 720px;
}

.gantt__head,
.gantt__row {
  display: flex;
  align-items: center;
}

.gantt__head {
  height: 32px;
  border-bottom: 1px solid v.$line;
}

.gantt__head-label {
  flex: 0 0 var(--gantt-label);
  padding-right: v.$sp-2;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.gantt__head-track {
  position: relative;
  flex: 1;
  height: 100%;
}

.gantt__tick {
  position: absolute;
  top: 0;
  height: 100%;
  border-left: 1px solid v.$line-soft;

  &.is-year {
    border-left-color: v.$line-strong;
  }
}

.gantt__tick-label {
  position: absolute;
  top: 2px;
  left: 4px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
  font-family: v.$font-num;
  white-space: nowrap;
}

.gantt__tick-sub {
  display: none;
}

.gantt__body {
  padding: 4px 0;
}

.gantt__row {
  height: 34px;

  &:hover {
    background: v.$surface-hover;
  }
}

.gantt__label {
  flex: 0 0 var(--gantt-label);
  padding: 0 v.$sp-2 0 0;
  border: none;
  background: none;
  text-align: left;
  font-size: v.$fs-sm;
  color: v.$ink-700;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    color: v.$brand-700;
    text-decoration: underline;
  }
}

.gantt__track {
  position: relative;
  flex: 1;
  height: 100%;
}

.gantt__grid {
  position: absolute;
  top: 0;
  height: 100%;
  border-left: 1px solid v.$line-soft;

  &.is-year {
    border-left-color: v.$line-strong;
  }
}

.gantt__bar {
  position: absolute;
  top: 7px;
  height: 20px;
  min-width: 8px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: v.$surface-sunken;
  overflow: hidden;
  cursor: pointer;
}

.gantt__bar-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: currentColor;
  opacity: 0.85;
}

.gantt__bar--brand { color: v.$brand-600; background: v.$brand-100; }
.gantt__bar--ok { color: v.$ok; background: v.$ok-bg; }
.gantt__bar--warn { color: v.$warn; background: v.$warn-bg; }
.gantt__bar--danger { color: v.$danger; background: v.$danger-bg; }

.gantt__bar-text {
  position: relative;
  z-index: 1;
  font-family: v.$font-num;
  font-size: 10px;
  color: v.$ink-900;
  mix-blend-mode: luminosity;
}

.gantt__today-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 0;
  border-left: 2px dashed v.$danger;
  opacity: 0.7;
  pointer-events: none;
}

.gantt__today-head {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 0;
  border-left: 2px dashed v.$danger;
  pointer-events: none;
}

.gantt__today-tag {
  position: absolute;
  top: 4px;
  left: 2px;
  padding: 0 5px;
  border-radius: 999px;
  background: v.$danger;
  color: #fff;
  font-size: 10px;
  line-height: 14px;
  white-space: nowrap;
}

.gantt__tip {
  font-size: v.$fs-sm;
  line-height: 1.7;
}

.gantt__legend {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  flex-wrap: wrap;
  margin-top: v.$sp-2;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.gantt__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.gantt__legend-hint {
  color: v.$ink-400;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.dot--brand { background: v.$brand-600; }
.dot--ok { background: v.$ok; }
.dot--warn { background: v.$warn; }
.dot--danger { background: v.$danger; }

@include bp.mobile {
  .gantt {
    --gantt-label: 104px;
  }

  .gantt__inner {
    min-width: 640px;
  }
}
</style>
