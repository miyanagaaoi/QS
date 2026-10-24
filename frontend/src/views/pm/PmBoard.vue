<script setup>
/**
 * PmBoard — 项目管理 · 首页看板（CH-002）
 * ---------------------------------------------------------------------------
 * 设计要求（需求方 2026-10-24）：快速实现、手工维护关键数据、看板汇总主要关键指标。
 *
 * 数据来源：GET /api/pm/board 一次拉取（summary + stage_distribution + projects + upcoming）
 *  - 进度由**后端按日期计算**（已过天数 ÷ 开工至计划竣工跨度），前端只展示，避免两套口径；
 *  - 当前阶段由用户在项目表单里手工维护（计划与实际分开表达）。
 *
 * 与报价模块**无任何关联**：本页不引用 rfq 数据。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createProject,
  deleteProject,
  exportPmBoard,
  getPmBoard,
  updateProject,
} from '@/api/pm'
import { useBreakpoint } from '@/composables/useBreakpoint'
import PmGantt from './PmGantt.vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const { isMobile } = useBreakpoint()
const userStore = useUserStore()

const loading = ref(true)
const exporting = ref(false)
const ganttOpen = ref(true)
const board = reactive({
  summary: { total: 0, active: 0, planning: 0, done: 0, paused: 0, overdue: 0, due_soon: 0 },
  stage_distribution: [],
  projects: [],
  upcoming: [],
})

const STAGES = [
  '决策立项', '勘察设计', '招标签约', '施工准备',
  '施工实施', '调试验收', '竣工验收', '缺陷保修',
]
const STATUS_OPTIONS = [
  { value: 'planning', label: '未开工' },
  { value: 'active', label: '进行中' },
  { value: 'done', label: '已竣工' },
  { value: 'paused', label: '暂停' },
]
const STATUS_LABEL = Object.fromEntries(STATUS_OPTIONS.map((x) => [x.value, x.label]))
const STATUS_TONE = {
  planning: 'muted',
  active: 'brand',
  done: 'ok',
  paused: 'warn',
}

const keyword = ref('')
const filtered = computed(() => {
  const k = keyword.value.trim()
  if (!k) return board.projects
  return board.projects.filter((p) =>
    [p.name, p.code, p.manager, p.current_stage].filter(Boolean).some((v) => String(v).includes(k)),
  )
})

const statCards = computed(() => [
  { key: 'total', label: '项目总数', value: board.summary.total, tone: 'brand' },
  { key: 'active', label: '进行中', value: board.summary.active, tone: 'brand' },
  { key: 'done', label: '已竣工', value: board.summary.done, tone: 'ok' },
  { key: 'overdue', label: '已超期', value: board.summary.overdue, tone: 'danger' },
  { key: 'due_soon', label: '30 天内到期', value: board.summary.due_soon, tone: 'warn' },
])

async function load() {
  loading.value = true
  try {
    const data = await getPmBoard()
    board.summary = data.summary || board.summary
    board.stage_distribution = data.stage_distribution || []
    board.projects = data.projects || []
    board.upcoming = data.upcoming || []
  } catch {
    // request.js 已统一 Toast
  } finally {
    loading.value = false
  }
}

/** 导出多项目进度清单（xlsx） */
async function exportBoard() {
  exporting.value = true
  try {
    await exportPmBoard(board.projects.length)
  } catch {
    // request.js 已提示
  } finally {
    exporting.value = false
  }
}

// —— 新建 / 编辑项目 ——
const dialog = reactive({
  visible: false,
  mode: 'create',
  saving: false,
  form: emptyForm(),
})

function emptyForm() {
  return {
    id: null,
    name: '',
    code: '',
    current_stage: '',
    start_date: '',
    plan_end_date: '',
    total_months: '',
    manager: '',
    status: 'active',
    remark: '',
  }
}

function openCreate() {
  dialog.mode = 'create'
  dialog.form = emptyForm()
  dialog.visible = true
}

function openEdit(row) {
  dialog.mode = 'edit'
  dialog.form = {
    id: row.id,
    name: row.name || '',
    code: row.code || '',
    current_stage: row.current_stage || '',
    start_date: row.start_date || '',
    plan_end_date: row.plan_end_date || '',
    total_months: row.total_months || '',
    manager: row.manager || '',
    status: row.status || 'active',
    remark: row.remark || '',
  }
  dialog.visible = true
}

async function submit() {
  const f = dialog.form
  if (!f.name.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  if (f.start_date && f.plan_end_date && f.plan_end_date < f.start_date) {
    ElMessage.warning('计划竣工日期不能早于开工日期')
    return
  }
  dialog.saving = true
  try {
    const payload = { ...f }
    delete payload.id
    if (!payload.start_date) payload.start_date = null
    if (!payload.plan_end_date) payload.plan_end_date = null
    if (dialog.mode === 'create') {
      await createProject(payload)
      ElMessage.success('项目已创建（已自动生成 8 阶段工期计划表）')
    } else {
      await updateProject(f.id, payload)
      ElMessage.success('项目已保存')
    }
    dialog.visible = false
    await load()
  } catch {
    // 后端原文已由 request.js 提示
  } finally {
    dialog.saving = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目「${row.name}」？其工期计划表会一并删除（不可恢复）。`,
      '删除项目',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deleteProject(row.id)
    ElMessage.success('项目已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      // 非管理员会收到 40300 原文提示
    }
  }
}

/** 手机端「更多」下拉的命令分发 */
function onRowCommand(command, row) {
  if (command === 'edit') openEdit(row)
  else if (command === 'remove') remove(row)
}

function openDetail(row) {
  router.push(`/pm/projects/${row.id}`)
}

/** 甘特图只发出项目 id（没有整行对象），单独处理跳转 */
function openById(id) {
  if (id) router.push(`/pm/projects/${id}`)
}

// —— 展示辅助 ——
function fmtMonths(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function progressTone(row) {
  if (row.overdue) return 'danger'
  if (row.status === 'done') return 'ok'
  if (row.due_soon) return 'warn'
  return 'brand'
}

function remainText(row) {
  if (row.remaining_days === null || row.remaining_days === undefined) return '未设计划竣工'
  if (row.status === 'done') return '已竣工'
  if (row.remaining_days < 0) return `超期 ${Math.abs(row.remaining_days)} 天`
  return `剩 ${row.remaining_days} 天`
}

onMounted(load)
</script>

<template>
  <div class="pm-board">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">项目管理</h2>
        <p class="page-head__sub">多项目进度看板 · 手工维护关键数据 · 与报价模块相互独立</p>
      </div>
      <div class="page-head__actions">
        <el-input
          v-model="keyword"
          placeholder="搜索项目 / 编号 / 项目经理"
          clearable
          style="width: 240px"
        />
        <el-button :loading="exporting" @click="exportBoard">导出 Excel</el-button>
        <el-button type="primary" @click="openCreate">+ 新建项目</el-button>
      </div>
    </header>

    <!-- 关键指标 -->
    <section v-loading="loading" class="stat-grid">
      <div v-for="card in statCards" :key="card.key" :class="['stat-card', `tone-${card.tone}`]">
        <div class="stat-card__label">{{ card.label }}</div>
        <div class="stat-card__value">{{ card.value }}</div>
      </div>
    </section>

    <!-- 阶段分布 + 近期节点 -->
    <section class="panel-grid">
      <div class="card">
        <div class="card__head">
          <h3 class="card__title">阶段分布</h3>
          <span class="card__hint">按各项目「当前阶段」统计</span>
        </div>
        <div v-if="board.stage_distribution.length" class="chips">
          <span v-for="item in board.stage_distribution" :key="item.stage" class="chip">
            {{ item.stage }}<b>{{ item.count }}</b>
          </span>
        </div>
        <p v-else class="empty-text">暂无项目</p>
      </div>

      <div class="card">
        <div class="card__head">
          <h3 class="card__title">近期关键节点</h3>
          <span class="card__hint">按计划竣工日期由近到远</span>
        </div>
        <ul v-if="board.upcoming.length" class="upcoming">
          <li v-for="item in board.upcoming" :key="item.id">
            <button class="link" type="button" @click="openDetail(item)">
              {{ item.name }}
            </button>
            <span :class="['upcoming__days', item.remaining_days < 0 ? 'is-over' : '']">
              {{ remainText(item) }}
            </span>
            <span class="upcoming__date">{{ item.plan_end_date || '—' }}</span>
          </li>
        </ul>
        <p v-else class="empty-text">暂无已设计划竣工日期的项目</p>
      </div>
    </section>

    <!-- 甘特图（CH-009，可折叠、只读） -->
    <section class="card gantt-panel">
      <div class="card__head gantt-panel__head">
        <h3 class="card__title">多项目进度甘特图</h3>
        <span class="card__hint">横轴按日期 · 数据来自各项目开工/计划竣工 · 只读</span>
        <el-button link type="primary" @click="ganttOpen = !ganttOpen">
          {{ ganttOpen ? '收起' : '展开' }}
        </el-button>
      </div>
      <div v-show="ganttOpen">
        <PmGantt :projects="board.projects" @open="openById" />
      </div>
    </section>

    <!-- 项目清单 -->
    <section class="card">
      <div class="card__head">
        <h3 class="card__title">项目进度</h3>
        <span class="card__hint">共 {{ filtered.length }} 个</span>
      </div>

      <el-table :data="filtered" stripe style="width: 100%" row-key="id">
        <el-table-column prop="name" label="项目名称" min-width="180">
          <template #default="{ row }">
            <button class="link" type="button" @click="openDetail(row)">{{ row.name }}</button>
            <div v-if="row.code" class="sub">{{ row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="current_stage" label="当前阶段" width="110">
          <template #default="{ row }">{{ row.current_stage || '未设置' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span :class="['badge', `badge--${STATUS_TONE[row.status] || 'muted'}`]">
              {{ STATUS_LABEL[row.status] || row.status }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="工期(月)" width="90" align="right">
          <template #default="{ row }">{{ fmtMonths(row.total_months) }}</template>
        </el-table-column>
        <el-table-column prop="start_date" label="开工日期" width="112">
          <template #default="{ row }">{{ row.start_date || '—' }}</template>
        </el-table-column>
        <el-table-column prop="plan_end_date" label="计划竣工" width="112">
          <template #default="{ row }">{{ row.plan_end_date || '—' }}</template>
        </el-table-column>
        <el-table-column label="总体进度" min-width="150">
          <template #default="{ row }">
            <div class="bar">
              <div
                :class="['bar__fill', `bar__fill--${progressTone(row)}`]"
                :style="{ width: `${row.progress}%` }"
              />
              <span class="bar__text">{{ row.progress }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="剩余" width="110">
          <template #default="{ row }">
            <span :class="row.overdue ? 'is-over' : ''">{{ remainText(row) }}</span>
          </template>
        </el-table-column>
        <!-- CH-005：施工工序完成度（工序状态独立于阶段表，只作参考） -->
        <el-table-column label="工序" width="86" align="center">
          <template #default="{ row }">
            <span class="process-count">
              {{ row.process_done ?? 0 }}<i>/{{ row.process_total ?? 0 }}</i>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="manager" label="项目经理" width="100">
          <template #default="{ row }">{{ row.manager || '—' }}</template>
        </el-table-column>
        <!-- 操作列：桌面一行放三项（列宽 200 才放得下：76+34+34+间距）；
             手机端受屏宽限制，收进「更多」下拉，避免按钮换行错位 -->
        <el-table-column label="操作" :width="isMobile ? 148 : 200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">工期计划表</el-button>
            <template v-if="!isMobile">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button
                v-if="userStore.isAdmin"
                link
                type="danger"
                @click="remove(row)"
              >
                删除
              </el-button>
            </template>
            <el-dropdown v-else trigger="click" @command="(cmd) => onRowCommand(cmd, row)">
              <el-button link type="primary">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item v-if="userStore.isAdmin" command="remove" divided>
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">还没有项目，点右上角「+ 新建项目」开始</div>
        </template>
      </el-table>
    </section>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'create' ? '新建项目' : '编辑项目'"
      width="620px"
      :close-on-click-modal="false"
    >
      <el-form label-width="104px" label-position="right">
        <el-form-item label="项目名称" required>
          <el-input v-model="dialog.form.name" maxlength="100" placeholder="如：忻州热力天然气补能项目" />
        </el-form-item>
        <el-form-item label="项目编号">
          <el-input v-model="dialog.form.code" maxlength="40" placeholder="选填，如 XZ-RL-2026" />
        </el-form-item>
        <el-form-item label="当前阶段">
          <el-select v-model="dialog.form.current_stage" clearable placeholder="未设置" style="width: 100%">
            <el-option v-for="s in STAGES" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="dialog.form.status" style="width: 100%">
            <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="开工日期">
          <el-date-picker v-model="dialog.form.start_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计划竣工">
          <el-date-picker v-model="dialog.form.plan_end_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="总工期(月)">
          <el-input v-model="dialog.form.total_months" placeholder="选填，如 24" />
        </el-form-item>
        <el-form-item label="项目经理">
          <el-input v-model="dialog.form.manager" maxlength="50" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.form.remark" type="textarea" :rows="2" maxlength="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-board {
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
  gap: v.$sp-2;
}

.gantt-panel__head {
  align-items: center;

  :deep(.el-button) {
    margin-left: auto;
  }
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
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
.tone-ok { border-left-color: v.$ok; }
.tone-warn { border-left-color: v.$warn; }
.tone-danger { border-left-color: v.$danger; }

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

.card__head {
  display: flex;
  align-items: baseline;
  gap: v.$sp-2;
  margin-bottom: v.$sp-3;
}

.card__title {
  margin: 0;
  font-size: v.$fs-lg;
}

.card__hint {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: v.$sp-2;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: v.$brand-50;
  color: v.$brand-800;
  border-radius: 999px;
  font-size: v.$fs-sm;

  b {
    font-family: v.$font-num;
  }
}

.upcoming {
  margin: 0;
  padding: 0;
  list-style: none;

  li {
    display: flex;
    align-items: center;
    gap: v.$sp-2;
    padding: 6px 0;
    border-bottom: 1px dashed v.$line-soft;
    font-size: v.$fs-sm;

    &:last-child { border-bottom: none; }
  }
}

.upcoming__days {
  margin-left: auto;
  font-family: v.$font-num;

  &.is-over { color: v.$danger; }

.process-count {
  font-family: v.$font-num;
  color: v.$ok;

  i {
    font-style: normal;
    color: v.$ink-400;
  }
}
}

.upcoming__date {
  color: v.$ink-400;
  font-family: v.$font-num;
  font-size: v.$fs-xs;
}

.link {
  padding: 0;
  border: none;
  background: none;
  color: v.$brand-700;
  font-size: inherit;
  cursor: pointer;
  text-align: left;

  &:hover { text-decoration: underline; }
}

.sub {
  font-size: v.$fs-xs;
  color: v.$ink-400;
  font-family: v.$font-num;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: v.$fs-xs;
  border: 1px solid transparent;
}

.badge--brand { background: v.$brand-50; color: v.$brand-800; border-color: v.$brand-100; }
.badge--ok { background: v.$ok-bg; color: v.$ok; border-color: v.$ok-line; }
.badge--warn { background: v.$warn-bg; color: v.$warn; border-color: v.$warn-line; }
.badge--danger { background: v.$danger-bg; color: v.$danger; border-color: v.$danger-line; }
.badge--muted { background: v.$muted-bg; color: v.$muted; border-color: v.$muted-line; }

.bar {
  position: relative;
  height: 8px;
  background: v.$surface-sunken;
  border-radius: 999px;
  overflow: visible;
}

.bar__fill {
  height: 100%;
  border-radius: 999px;
  background: v.$brand-600;
}

.bar__fill--ok { background: v.$ok; }
.bar__fill--warn { background: v.$warn; }
.bar__fill--danger { background: v.$danger; }

.bar__text {
  position: absolute;
  right: 0;
  top: -16px;
  font-family: v.$font-num;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.is-over { color: v.$danger; }

.empty-text {
  margin: 0;
  padding: v.$sp-3 0;
  color: v.$ink-400;
  font-size: v.$fs-sm;
  text-align: center;
}

@include bp.mobile {
  .page-head {
    flex-direction: column;
  }

  .page-head__actions {
    margin-left: 0;
    width: 100%;

    :deep(.el-input) { flex: 1; }
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-grid {
    grid-template-columns: 1fr;
  }
}
</style>
