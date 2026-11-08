<script setup>
/**
 * EqBoard — 设备管理 · 统计看板（CH-014）
 * ---------------------------------------------------------------------------
 * 对应 Excel 模板的「统计看板」sheet，4 组统计全部由各台账实时汇总：
 *   ① 设备总量与状态分布（9 种状态）② 按重要等级分布
 *   ③ 到期预警 7 项（质保 30 天/检定检验 15 天/计划事项逾期）
 *   ④ 动态事件统计（11 类 + 本年度）
 * 数字全部来自 `GET /api/eq/board`，前端只做条形百分比展示。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getEqBoard } from '@/api/equipment'

const router = useRouter()
const loading = ref(false)
const board = ref({
  total: 0,
  by_status: [],
  by_importance: [],
  warnings: [],
  event_total: 0,
  by_event_type: [],
  events_this_year: 0,
})

const warnTotal = computed(() => board.value.warnings.reduce((s, w) => s + (w.count || 0), 0))

function pct(item) {
  return Math.round((item.ratio || 0) * 1000) / 10
}

async function load() {
  loading.value = true
  try {
    board.value = await getEqBoard()
  } catch {
    /* 已提示 */
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="eq-board">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">设备管理统计看板</h2>
        <p class="page-head__sub">数据随各台账自动汇总 · 质保 ≤30 天、检定/检验 ≤15 天进入预警</p>
      </div>
      <div class="page-head__actions">
        <el-button size="small" @click="router.push('/eq/assets')">去设备台账</el-button>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </header>

    <section class="stat-grid">
      <div class="stat-card">
        <div class="stat-card__label">设备总数</div>
        <div class="stat-card__value">{{ board.total }}</div>
      </div>
      <div class="stat-card tone-warn">
        <div class="stat-card__label">预警合计</div>
        <div class="stat-card__value">{{ warnTotal }}</div>
      </div>
      <div class="stat-card tone-brand">
        <div class="stat-card__label">事件记录</div>
        <div class="stat-card__value">{{ board.event_total }}</div>
      </div>
      <div class="stat-card tone-ok">
        <div class="stat-card__label">本年度事件</div>
        <div class="stat-card__value">{{ board.events_this_year }}</div>
      </div>
    </section>

    <section class="panel-grid">
      <div class="card">
        <h3 class="card__title">一、设备状态分布</h3>
        <div v-for="item in board.by_status" :key="item.label" class="bar-row">
          <span class="bar-row__label">{{ item.label }}</span>
          <div class="bar">
            <div class="bar__fill" :style="{ width: `${Math.max(pct(item), item.count ? 2 : 0)}%` }" />
          </div>
          <span class="bar-row__num">{{ item.count }}（{{ pct(item) }}%）</span>
        </div>
      </div>

      <div class="card">
        <h3 class="card__title">二、按重要等级分布</h3>
        <div v-for="item in board.by_importance" :key="item.label" class="bar-row">
          <span class="bar-row__label">{{ item.label }}</span>
          <div class="bar">
            <div class="bar__fill bar__fill--brand" :style="{ width: `${Math.max(pct(item), item.count ? 2 : 0)}%` }" />
          </div>
          <span class="bar-row__num">{{ item.count }}（{{ pct(item) }}%）</span>
        </div>
      </div>
    </section>

    <section class="card">
      <h3 class="card__title">三、到期预警（需本周内处理）</h3>
      <el-table :data="board.warnings" border size="small">
        <el-table-column prop="label" label="预警项" min-width="220" />
        <el-table-column prop="count" label="数量" width="90" align="center">
          <template #default="{ row }">
            <span :class="['num', row.count ? 'is-over' : '']">{{ row.count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="处理要求" min-width="180" />
      </el-table>
    </section>

    <section class="card">
      <h3 class="card__title">四、动态事件记录统计</h3>
      <div class="event-grid">
        <div v-for="item in board.by_event_type" :key="item.label" class="event-item">
          <span class="event-item__label">{{ item.label }}</span>
          <span class="event-item__num">{{ item.count }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.eq-board {
  display: flex;
  flex-direction: column;
  gap: v.$sp-4;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-3;
}

.page-head__title {
  margin: 0;
  font-size: v.$fs-title;
}

.page-head__sub {
  margin: 3px 0 0;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.page-head__actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: v.$sp-3;
}

.stat-card {
  padding: v.$sp-3 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-left: 3px solid v.$line-strong;
  border-radius: v.$r-md;
}

.stat-card__label {
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.stat-card__value {
  margin-top: 4px;
  font-family: v.$font-num;
  font-size: 24px;
  font-weight: 600;
  color: v.$ink-900;
}

.tone-brand { border-left-color: v.$brand-600; }
.tone-warn { border-left-color: v.$warn; }
.tone-ok { border-left-color: v.$ok; }

.panel-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: v.$sp-3;
}

.card {
  padding: v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.card__title {
  margin: 0 0 v.$sp-3;
  font-size: v.$fs-lg;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  margin-bottom: 8px;
}

.bar-row__label {
  width: 70px;
  font-size: v.$fs-sm;
  color: v.$ink-500;
  flex: 0 0 auto;
}

.bar {
  flex: 1;
  height: 8px;
  background: v.$surface-sunken;
  border-radius: 999px;
  overflow: hidden;
}

.bar__fill {
  height: 100%;
  background: v.$brand-600;
  border-radius: 999px;
}

.bar__fill--brand {
  background: v.$brand-500;
}

.bar-row__num {
  width: 110px;
  text-align: right;
  font-family: v.$font-num;
  font-size: v.$fs-xs;
  color: v.$ink-400;
  flex: 0 0 auto;
}

.num {
  font-family: v.$font-num;
}

.is-over {
  color: v.$danger;
  font-weight: 600;
}

.event-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: v.$sp-2;
}

.event-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: v.$surface-sunken;
  border-radius: v.$r-sm;
  font-size: v.$fs-sm;
}

.event-item__label {
  color: v.$ink-500;
}

.event-item__num {
  font-family: v.$font-num;
  color: v.$ink-900;
  font-weight: 600;
}

@include bp.mobile {
  .page-head {
    flex-direction: column;
  }

  .page-head__actions {
    margin-left: 0;
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-grid {
    grid-template-columns: 1fr;
  }

  .event-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
