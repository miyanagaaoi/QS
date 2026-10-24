<script setup>
/**
 * PmProcesses — 项目管理 · 施工实施步骤明细（CH-005）
 * ---------------------------------------------------------------------------
 * 数据分两层：
 *  - **项目副本**（默认）：某个项目的 15 道工序，带进度状态，项目内可增删改；
 *  - **标准模板**（仅管理员）：全公司一套，新建项目时按它复制。
 *
 * 进度（FR-PM-19~26）：
 *  - 四态：未开始 / 进行中 / 已完成 / 暂停，**允许多道并行进行中**；
 *  - 行内状态按钮按当前状态给出下一步动作（开始/完成/暂停/恢复/重开）；
 *  - 每次变更写一条历史（后端 `pm_process_log`，只追加不可改），行内「历史」抽屉查看；
 *  - 实际开始/完成时间由后端按状态自动写入，前端只展示。
 *
 * 接口：/api/pm/processes?project_id=…、POST /{id}/status、GET /{id}/logs
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  changePmProcessStatus,
  createPmProcess,
  deletePmProcess,
  listPmProcesses,
  listPmProcessLogs,
  resetProjectCopies,
  updatePmProcess,
  updatePmProcessProgress,
} from '@/api/pm'
import { usePmScope } from '@/composables/usePmScope'
import PmScopeBar from './PmScopeBar.vue'

const {
  isAdmin,
  projects,
  loadingProjects,
  mode,
  projectId,
  scopeKey,
  isTemplate,
  currentProject,
  setMode,
  setProjectId,
  loadProjects,
} = usePmScope()

const loading = ref(false)
const rows = ref([])

const STATUS = {
  todo: { label: '未开始', tone: 'muted' },
  doing: { label: '进行中', tone: 'brand' },
  done: { label: '已完成', tone: 'ok' },
  paused: { label: '暂停', tone: 'warn' },
}

/** 每个状态下可执行的下一步动作（done 允许"重开"，现场返工常见） */
const ACTIONS = {
  todo: [{ to: 'doing', label: '开始', type: 'primary' }],
  doing: [
    { to: 'done', label: '完成', type: 'success' },
    { to: 'paused', label: '暂停', type: 'warning' },
  ],
  paused: [{ to: 'doing', label: '恢复', type: 'primary' }],
  done: [{ to: 'doing', label: '重开', type: 'info' }],
}

const summary = computed(() => {
  const total = rows.value.length
  const done = rows.value.filter((r) => r.status === 'done').length
  const doing = rows.value.filter((r) => r.status === 'doing')
  const paused = rows.value.filter((r) => r.status === 'paused').length
  return {
    total,
    done,
    doingCount: doing.length,
    paused,
    todo: total - done - doing.length - paused,
    percent: total ? Math.round((done / total) * 100) : 0,
    current: doing.map((r) => r.name),
  }
})

async function load() {
  loading.value = true
  try {
    rows.value = await listPmProcesses(scopeKey.value)
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(scopeKey, load)

function statusOf(row) {
  return STATUS[row.status] || STATUS.todo
}

function actionsOf(row) {
  return ACTIONS[row.status] || []
}

/** 状态变更：弹框可填一句备注（FR-PM-21），确认后由后端写历史 */
async function changeStatus(row, action) {
  const label = STATUS[action.to]?.label || action.to
  let remark = ''
  try {
    const result = await ElMessageBox.prompt(
      `将「${row.name}」由「${statusOf(row).label}」改为「${label}」。备注可不填。`,
      '变更工序状态',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：监理验收通过 / 材料未到暂停',
        inputType: 'text',
        inputValidator: (value) => (value && value.length > 200 ? '备注不超过 200 字' : true),
      },
    )
    remark = result.value || ''
  } catch {
    return // 用户取消
  }
  try {
    const updated = await changePmProcessStatus(row.id, action.to, remark)
    const index = rows.value.findIndex((r) => r.id === row.id)
    if (index >= 0) rows.value[index] = updated
    ElMessage.success(`已改为「${label}」`)
  } catch {
    // 后端原文提示（如"状态未发生变化"）
  }
}

// —— 进度更新（CH-006：仅"进行中"可用）——
const progressDialog = reactive({ visible: false, saving: false, row: null, remark: '' })

function openProgress(row) {
  progressDialog.row = row
  progressDialog.remark = row.progress_remark || ''
  progressDialog.visible = true
}

async function submitProgress() {
  const remark = progressDialog.remark.trim()
  if (!remark) return ElMessage.warning('请填写本次进度说明')
  progressDialog.saving = true
  try {
    const updated = await updatePmProcessProgress(progressDialog.row.id, remark)
    const index = rows.value.findIndex((r) => r.id === progressDialog.row.id)
    if (index >= 0) rows.value[index] = updated
    progressDialog.visible = false
    ElMessage.success('进度已更新')
  } catch {
    /* 已提示 */
  } finally {
    progressDialog.saving = false
  }
}

// —— 编辑 / 新增 ——
const dialog = reactive({ visible: false, saving: false, mode: 'edit', form: emptyForm() })

function emptyForm() {
  return {
    id: null,
    seq: '',
    group_name: '',
    name: '',
    content: '',
    qc_point: '',
    predecessor: '',
    assignee: '',
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
    seq: row.seq,
    group_name: row.group_name || '',
    name: row.name || '',
    content: row.content || '',
    qc_point: row.qc_point || '',
    predecessor: row.predecessor || '',
    assignee: row.assignee || '',
  }
  dialog.visible = true
}

async function submit() {
  if (!dialog.form.name.trim()) return ElMessage.warning('请填写工序名称')
  if (!dialog.form.group_name.trim()) return ElMessage.warning('请填写工序分组')
  dialog.saving = true
  try {
    const payload = {
      seq: dialog.form.seq === '' ? null : Number(dialog.form.seq),
      group_name: dialog.form.group_name.trim(),
      name: dialog.form.name.trim(),
      content: dialog.form.content || null,
      qc_point: dialog.form.qc_point || null,
      predecessor: dialog.form.predecessor || null,
      assignee: dialog.form.assignee || null,
    }
    if (dialog.mode === 'create') {
      await createPmProcess(payload, scopeKey.value)
      ElMessage.success('已新增工序')
    } else {
      await updatePmProcess(dialog.form.id, payload)
      ElMessage.success('已保存')
    }
    dialog.visible = false
    await load()
  } catch {
    /* 已提示 */
  } finally {
    dialog.saving = false
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除工序「${row.name}」？其变更历史会一并删除，且不影响标准模板。`,
      '删除工序',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deletePmProcess(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* 取消或被后端拒绝 */
  }
}

// —— 变更历史抽屉 ——
const history = reactive({ visible: false, loading: false, row: null, logs: [] })

async function openHistory(row) {
  history.row = row
  history.visible = true
  history.loading = true
  history.logs = []
  try {
    history.logs = await listPmProcessLogs(row.id)
  } catch {
    /* 已提示 */
  } finally {
    history.loading = false
  }
}

function fmtTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function resetCopies() {
  if (!projectId.value) return
  try {
    await ElMessageBox.confirm(
      `按标准模板重置「${currentProject.value?.name || ''}」的工序/管理点/单据三项？该项目的自定义修改会丢失。`,
      '按模板重置',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
    await resetProjectCopies(projectId.value)
    ElMessage.success('已按模板重置')
    await load()
  } catch {
    /* 取消 */
  }
}

onMounted(async () => {
  await loadProjects()
  await load()
})
</script>

<template>
  <div class="pm-processes">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">施工实施步骤明细</h2>
        <p class="page-head__sub">
          {{ isTemplate ? '标准模板（全公司一套，新建项目时按它复制）' : '项目工序进度（可逐条维护状态与负责人）' }}
        </p>
      </div>
      <div class="page-head__actions">
        <el-button @click="openCreate">+ 新增工序</el-button>
      </div>
    </header>

    <PmScopeBar
      :projects="projects"
      :project-id="projectId"
      :mode="mode"
      :is-admin="isAdmin"
      :can-reset="!isTemplate"
      @update:project-id="setProjectId"
      @update:mode="setMode"
      @reset="resetCopies"
    />

    <!-- 当前进度汇总（FR-PM-24） -->
    <section v-if="!isTemplate" class="summary-card">
      <div class="summary-card__main">
        <span class="summary-card__num">{{ summary.done }}<i>/{{ summary.total }}</i></span>
        <div class="summary-card__meta">
          <div class="summary-card__title">已完成工序</div>
          <div class="summary-card__bar">
            <div class="summary-card__bar-fill" :style="{ width: `${summary.percent}%` }" />
          </div>
        </div>
      </div>
      <div class="summary-card__items">
        <span class="pill pill--brand">进行中 {{ summary.doingCount }}</span>
        <span class="pill pill--warn">暂停 {{ summary.paused }}</span>
        <span class="pill pill--muted">未开始 {{ summary.todo }}</span>
        <span v-if="summary.current.length" class="summary-card__now">
          当前进行：{{ summary.current.slice(0, 3).join('、') }}{{ summary.current.length > 3 ? ' 等' : '' }}
        </span>
      </div>
    </section>

    <section v-loading="loading || loadingProjects" class="card">
      <el-table :data="rows" border size="small" style="width: 100%" row-key="id">
        <el-table-column prop="seq" label="序号" width="60" align="center" />
        <el-table-column prop="group_name" label="工序分组" width="110" />
        <el-table-column prop="name" label="工序名称" min-width="150" />
        <el-table-column label="负责人" width="110">
          <template #default="{ row }">{{ row.assignee || '—' }}</template>
        </el-table-column>
        <el-table-column label="当前状态" width="300">
          <template #default="{ row }">
            <div class="status-cell">
              <span :class="['badge', `badge--${statusOf(row).tone}`]">{{ statusOf(row).label }}</span>
              <el-button
                v-if="row.status === 'doing'"
                link
                type="primary"
                @click="openProgress(row)"
              >
                更新
              </el-button>
              <el-button
                v-for="action in actionsOf(row)"
                :key="action.to"
                link
                :type="action.type"
                @click="changeStatus(row, action)"
              >
                {{ action.label }}
              </el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="实际开始" width="120">
          <template #default="{ row }"><span class="num">{{ fmtTime(row.started_at) }}</span></template>
        </el-table-column>
        <el-table-column label="实际完成" width="120">
          <template #default="{ row }"><span class="num">{{ fmtTime(row.finished_at) }}</span></template>
        </el-table-column>
        <el-table-column label="备注" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.progress_remark || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openHistory(row)">历史</el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">
            {{ isTemplate ? '标准模板为空' : '该项目暂无工序，点右上角「+ 新增工序」' }}
          </div>
        </template>
      </el-table>
    </section>

    <!-- 更新当前进度（CH-006） -->
    <el-dialog v-model="progressDialog.visible" title="更新当前进度" width="520px" :close-on-click-modal="false">
      <p class="progress-tip">
        「{{ progressDialog.row?.name || '' }}」当前状态：进行中。这里只记录进度说明，
        <b>不会改变工序状态</b>；每次更新都会写入变更历史。
      </p>
      <el-form label-position="top">
        <el-form-item label="本次进度说明" required>
          <el-input
            v-model="progressDialog.remark"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="例如：土方开挖完成 40%，边坡支护同步进行，预计 3 天后完成"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="progressDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="progressDialog.saving" @click="submitProgress">提交更新</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 / 新增 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'create' ? '新增工序' : '编辑工序'"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-form label-width="104px">
        <el-form-item label="序号">
          <el-input v-model="dialog.form.seq" placeholder="留空自动排到末尾" />
        </el-form-item>
        <el-form-item label="工序分组" required>
          <el-input
            v-model="dialog.form.group_name"
            maxlength="20"
            placeholder="土建工程 / 设备安装 / 电仪自控 / 防腐保温 / 试验检验"
          />
        </el-form-item>
        <el-form-item label="工序名称" required>
          <el-input v-model="dialog.form.name" maxlength="60" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="dialog.form.assignee" maxlength="50" placeholder="该工序现场负责人" />
        </el-form-item>
        <el-form-item label="主要工作内容">
          <el-input v-model="dialog.form.content" type="textarea" :rows="2" maxlength="400" />
        </el-form-item>
        <el-form-item label="质量控制点">
          <el-input v-model="dialog.form.qc_point" type="textarea" :rows="2" maxlength="300" />
        </el-form-item>
        <el-form-item label="紧前工序">
          <el-input v-model="dialog.form.predecessor" maxlength="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 变更历史 -->
    <el-drawer v-model="history.visible" :title="`变更历史 · ${history.row?.name || ''}`" size="420px">
      <div v-loading="history.loading">
        <el-timeline v-if="history.logs.length">
          <el-timeline-item
            v-for="log in history.logs"
            :key="log.id"
            :timestamp="fmtTime(log.created_at)"
            placement="top"
          >
            <!-- 进度更新（kind=progress）：状态不变，只展示进度说明 -->
            <div v-if="log.kind === 'progress'" class="log-line">
              <span class="badge badge--brand">进度更新</span>
              <span class="badge badge--brand">{{ STATUS[log.to_status]?.label || log.to_status }}</span>
            </div>
            <div v-else class="log-line">
              <span class="badge badge--muted">{{ STATUS[log.from_status]?.label || '—' }}</span>
              <span class="log-arrow">→</span>
              <span :class="['badge', `badge--${STATUS[log.to_status]?.tone || 'muted'}`]">
                {{ STATUS[log.to_status]?.label || log.to_status }}
              </span>
            </div>
            <div class="log-meta">操作人：{{ log.operator_name || '—' }}</div>
            <div v-if="log.remark" class="log-remark">{{ log.remark }}</div>
          </el-timeline-item>
        </el-timeline>
        <p v-else class="empty-text">暂无变更记录</p>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-processes {
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
}

.summary-card {
  display: flex;
  align-items: center;
  gap: v.$sp-4;
  padding: v.$sp-3 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.summary-card__main {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  min-width: 220px;
}

.summary-card__num {
  font-family: v.$font-num;
  font-size: 26px;
  font-weight: 600;
  color: v.$ink-900;

  i {
    font-size: 14px;
    font-style: normal;
    color: v.$ink-400;
  }
}

.summary-card__meta {
  flex: 1;
  min-width: 120px;
}

.summary-card__title {
  font-size: v.$fs-xs;
  color: v.$ink-500;
  margin-bottom: 4px;
}

.summary-card__bar {
  height: 6px;
  background: v.$surface-sunken;
  border-radius: 999px;
  overflow: hidden;
}

.summary-card__bar-fill {
  height: 100%;
  background: v.$ok;
  border-radius: 999px;
}

.summary-card__items {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

.summary-card__now {
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.pill {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: v.$fs-xs;
}

.pill--brand { background: v.$brand-50; color: v.$brand-800; }
.pill--warn { background: v.$warn-bg; color: v.$warn; }
.pill--muted { background: v.$muted-bg; color: v.$muted; }

.card {
  padding: v.$sp-3;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: v.$fs-xs;
  border: 1px solid transparent;
  white-space: nowrap;
}

.badge--brand { background: v.$brand-50; color: v.$brand-800; border-color: v.$brand-100; }
.badge--ok { background: v.$ok-bg; color: v.$ok; border-color: v.$ok-line; }
.badge--warn { background: v.$warn-bg; color: v.$warn; border-color: v.$warn-line; }
.badge--muted { background: v.$muted-bg; color: v.$muted; border-color: v.$muted-line; }

.num {
  font-family: v.$font-num;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.log-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.log-arrow {
  color: v.$ink-400;
}

.log-meta {
  margin-top: 4px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.log-remark {
  margin-top: 4px;
  font-size: v.$fs-sm;
  color: v.$ink-700;
}

.progress-tip {
  margin: 0 0 v.$sp-3;
  padding: v.$sp-2 v.$sp-3;
  background: v.$surface-sunken;
  border-radius: v.$r-sm;
  font-size: v.$fs-sm;
  color: v.$ink-500;

  b {
    color: v.$ink-900;
  }
}

.empty-text {
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

    :deep(.el-button) {
      width: 100%;
      min-height: v.$touch-target;
    }
  }

  .summary-card {
    flex-direction: column;
    align-items: stretch;
    gap: v.$sp-2;
  }

  .card {
    overflow-x: auto;
  }
}
</style>
