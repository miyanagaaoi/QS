<script setup>
/**
 * PmDocuments — 项目管理 · 预算决算配套单据（CH-007）
 * ---------------------------------------------------------------------------
 * 与 CH-005 相比的三处改造：
 *  1. **审批流转 = 节点列表**：编辑弹窗里手动增删/排序节点；
 *     列表页显示"当前节点 · n/m"，点击可推进或回退到任一节点（写历史）。
 *  2. **归档要求 = 文件清单**：编辑弹窗里逐个定义需要归档的文件
 *     （名称 + 备注）；列表页可逐项勾选归档、可追加文件。
 *  3. **列表页多选批量归档** + **小计**（已归档 x/12 张单据）；
 *     归档要求列显示一行摘要，鼠标悬停浮窗看每个文件的归档状态。
 *
 * 模板 vs 项目副本：模板只维护"节点 + 文件要求"，不跟踪当前节点与归档状态。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  addPmDocumentFile,
  batchPmDocumentArchive,
  changePmDocumentNode,
  createPmDocument,
  deletePmDocument,
  listPmDocumentLogs,
  listPmDocuments,
  resetProjectCopies,
  togglePmDocumentArchive,
  updatePmDocument,
} from '@/api/pm'
import { usePmScope } from '@/composables/usePmScope'
import PmScopeBar from './PmScopeBar.vue'

const {
  isAdmin, projects, loadingProjects, mode, projectId, scopeKey, isTemplate,
  currentProject, setMode, setProjectId, loadProjects,
} = usePmScope()

const rows = ref([])
const loading = ref(false)
const selected = ref([])

/** 小计：单据数 / 已归档单据数 / 归档文件完成数 */
const stats = computed(() => {
  const total = rows.value.length
  const archived = rows.value.filter((r) => r.archived).length
  const files = rows.value.reduce((sum, r) => sum + (r.archive_total || 0), 0)
  const filesDone = rows.value.reduce((sum, r) => sum + (r.archive_done || 0), 0)
  return { total, archived, files, filesDone }
})

async function load() {
  loading.value = true
  try {
    rows.value = await listPmDocuments(scopeKey.value)
    selected.value = []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

watch(scopeKey, load)

function onSelectionChange(list) {
  selected.value = list
}

// —— 审批节点：点击选择当前节点 ——
async function pickNode(row, node) {
  if (row.current_node === node) return
  try {
    const updated = await changePmDocumentNode(row.id, node)
    replaceRow(updated)
    ElMessage.success(`已推进到「${node}」`)
  } catch {
    /* 已提示 */
  }
}

function replaceRow(updated) {
  const index = rows.value.findIndex((r) => r.id === updated.id)
  if (index >= 0) rows.value[index] = updated
}

// —— 归档：逐项勾选 ——
const archiveDialog = reactive({ visible: false, row: null, saving: false })

function openArchive(row) {
  archiveDialog.row = row
  archiveDialog.visible = true
}

async function toggleFile(row, file) {
  archiveDialog.saving = true
  try {
    const updated = await togglePmDocumentArchive(row.id, file.name, !file.archived)
    replaceRow(updated)
    archiveDialog.row = updated
    if (updated.archived) ElMessage.success('该单据已全部归档')
  } catch {
    /* 已提示 */
  } finally {
    archiveDialog.saving = false
  }
}

// —— 多选批量归档 ——
async function batchArchive(archived) {
  if (!selected.value.length) return ElMessage.warning('请先勾选单据')
  try {
    await ElMessageBox.confirm(
      `把选中的 ${selected.value.length} 张单据的全部归档文件标记为${archived ? '已归档' : '未归档'}？`,
      archived ? '批量标记已归档' : '批量撤销归档',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
    const result = await batchPmDocumentArchive(selected.value.map((r) => r.id), archived)
    ElMessage.success(`已更新 ${result.updated} 张单据`)
    await load()
  } catch {
    /* 取消 */
  }
}

// —— 追加归档文件（列表页行内）——
const addFileDialog = reactive({ visible: false, row: null, saving: false, name: '', note: '' })

/** 从"归档勾选"弹窗里继续追加文件 */
function openAddFileFromArchive() {
  const row = archiveDialog.row
  archiveDialog.visible = false
  if (row) openAddFile(row)
}

function openAddFile(row) {
  addFileDialog.row = row
  addFileDialog.name = ''
  addFileDialog.note = ''
  addFileDialog.visible = true
}

async function submitAddFile() {
  const name = addFileDialog.name.trim()
  if (!name) return ElMessage.warning('请填写文件名')
  addFileDialog.saving = true
  try {
    const updated = await addPmDocumentFile(addFileDialog.row.id, {
      name,
      note: addFileDialog.note || null,
    })
    replaceRow(updated)
    addFileDialog.visible = false
    ElMessage.success('已追加归档文件')
  } catch {
    /* 已提示 */
  } finally {
    addFileDialog.saving = false
  }
}

// —— 编辑弹窗：节点列表 + 文件清单 ——
const dialog = reactive({ visible: false, saving: false, mode: 'edit', form: emptyForm() })

function emptyForm() {
  return {
    id: null, seq: '', cost_point: '', name: '', usage: '', required_fields: '',
    nodes: [''], files: [{ name: '', note: '' }],
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
    cost_point: row.cost_point || '',
    name: row.name || '',
    usage: row.usage || '',
    required_fields: row.required_fields || '',
    nodes: (row.flow_nodes || []).slice(),
    files: (row.archive_files || []).map((f) => ({ name: f.name, note: f.note || '' })),
  }
  if (!dialog.form.nodes.length) dialog.form.nodes = ['']
  if (!dialog.form.files.length) dialog.form.files = [{ name: '', note: '' }]
  dialog.visible = true
}

function addNode() {
  dialog.form.nodes.push('')
}
function removeNode(index) {
  dialog.form.nodes.splice(index, 1)
  if (!dialog.form.nodes.length) dialog.form.nodes.push('')
}
function moveNode(index, delta) {
  const target = index + delta
  const list = dialog.form.nodes
  if (target < 0 || target >= list.length) return
  ;[list[index], list[target]] = [list[target], list[index]]
}

function addFileRow() {
  dialog.form.files.push({ name: '', note: '' })
}
function removeFileRow(index) {
  dialog.form.files.splice(index, 1)
  if (!dialog.form.files.length) dialog.form.files.push({ name: '', note: '' })
}

async function submit() {
  if (!dialog.form.name.trim()) return ElMessage.warning('请填写单据名称')
  const nodes = dialog.form.nodes.map((n) => n.trim()).filter(Boolean)
  const files = dialog.form.files
    .map((f) => ({ name: f.name.trim(), note: f.note.trim() || null, required: true }))
    .filter((f) => f.name)
  if (new Set(nodes).size !== nodes.length) return ElMessage.warning('审批节点有重复')
  if (new Set(files.map((f) => f.name)).size !== files.length) return ElMessage.warning('归档文件有重复')

  dialog.saving = true
  try {
    const payload = {
      seq: dialog.form.seq === '' ? null : Number(dialog.form.seq),
      cost_point: dialog.form.cost_point || null,
      name: dialog.form.name.trim(),
      usage: dialog.form.usage || null,
      required_fields: dialog.form.required_fields || null,
      flow_nodes: nodes,
      archive_files: files,
    }
    if (dialog.mode === 'create') {
      await createPmDocument(payload, scopeKey.value)
      ElMessage.success('已新增单据')
    } else {
      await updatePmDocument(dialog.form.id, payload)
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
      `删除单据「${row.name}」？其节点/归档历史会一并删除，不影响标准模板。`,
      '删除单据',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await deletePmDocument(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* 取消 */
  }
}

// —— 历史 ——
const history = reactive({ visible: false, loading: false, row: null, logs: [] })

async function openHistory(row) {
  history.row = row
  history.visible = true
  history.loading = true
  history.logs = []
  try {
    history.logs = await listPmDocumentLogs(row.id)
  } catch {
    /* 已提示 */
  } finally {
    history.loading = false
  }
}

async function resetCopies() {
  if (!projectId.value) return
  try {
    await ElMessageBox.confirm(
      `按标准模板重置「${currentProject.value?.name || ''}」的工序/管理点/单据三项？该项目的自定义修改、节点与归档状态会丢失。`,
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

function fmtTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

/** 归档要求摘要（列窄，只显示"文件数 + 已归档数"，明细看悬停浮窗） */
function archiveSummary(row) {
  if (!row.archive_total) return '未定义'
  return `${row.archive_total} 个文件 · 已归档 ${row.archive_done}`
}

onMounted(async () => {
  await loadProjects()
  await load()
})
</script>

<template>
  <div class="pm-docs">
    <header class="page-head">
      <div>
        <h2 class="page-head__title">预算决算配套单据</h2>
        <p class="page-head__sub">
          {{ isTemplate
            ? '标准模板（只维护审批节点与归档文件要求，不跟踪进度）'
            : '点击节点推进审批；勾选归档文件；可多选批量归档' }}
        </p>
      </div>
      <div class="page-head__actions">
        <el-button @click="openCreate">+ 新增单据</el-button>
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

    <!-- 小计 + 批量操作 -->
    <section class="toolbar">
      <div class="toolbar__stats">
        <span class="stat">单据 <b>{{ stats.total }}</b></span>
        <span class="stat">已归档单据 <b class="ok">{{ stats.archived }}</b>/{{ stats.total }}</span>
        <span class="stat">归档文件 <b>{{ stats.filesDone }}</b>/{{ stats.files }}</span>
        <span v-if="selected.length" class="stat stat--sel">已选 {{ selected.length }} 张</span>
      </div>
      <div v-if="!isTemplate" class="toolbar__actions">
        <el-button size="small" :disabled="!selected.length" @click="batchArchive(true)">
          批量标记已归档
        </el-button>
        <el-button size="small" :disabled="!selected.length" @click="batchArchive(false)">
          撤销归档
        </el-button>
      </div>
    </section>

    <section v-loading="loading || loadingProjects" class="card">
      <el-table
        :data="rows"
        row-key="id"
        border
        size="small"
        style="width: 100%"
        @selection-change="onSelectionChange"
      >
        <el-table-column v-if="!isTemplate" type="selection" width="40" />
        <el-table-column prop="seq" label="序号" width="58" align="center" />
        <el-table-column prop="name" label="单据名称" min-width="170" />
        <el-table-column prop="cost_point" label="对应管理点" width="140">
          <template #default="{ row }">{{ row.cost_point || '—' }}</template>
        </el-table-column>

        <el-table-column prop="required_fields" label="核心栏目" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.required_fields || '—' }}</template>
        </el-table-column>

        <!-- 审批流转：显示当前节点，点击选择 -->
        <el-table-column label="审批节点" width="196">
          <template #default="{ row }">
            <div class="node-cell">
              <template v-if="row.flow_nodes.length">
                <span class="node-badge">{{ row.current_node || '未开始' }}</span>
                <span class="node-pos">
                  {{ row.current_node ? row.flow_nodes.indexOf(row.current_node) + 1 : 0 }}/{{ row.flow_nodes.length }}
                </span>
                <el-dropdown
                  v-if="!isTemplate"
                  trigger="click"
                  @command="(node) => pickNode(row, node)"
                >
                  <el-button link type="primary">选择</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-for="node in row.flow_nodes"
                        :key="node"
                        :command="node"
                        :disabled="node === row.current_node"
                      >
                        {{ node }}{{ node === row.current_node ? '（当前）' : '' }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </template>
              <span v-else class="muted">未定义节点</span>
            </div>
          </template>
        </el-table-column>

        <!-- 归档：只显示进度与一个入口，勾选/追加文件都在弹窗里做，避免列内拥挤 -->
        <el-table-column label="归档" width="104" align="center">
          <template #default="{ row }">
            <div class="archive-cell">
              <span :class="['arch-badge', row.archived ? 'is-done' : row.archive_done ? 'is-part' : '']">
                {{ row.archive_done }}/{{ row.archive_total }}
              </span>
              <el-button v-if="!isTemplate" link type="primary" @click="openArchive(row)">
                归档
              </el-button>
            </div>
          </template>
        </el-table-column>

        <!-- 归档要求：短摘要 + 悬停浮窗看明细（列窄，避免挤占其它列） -->
        <el-table-column label="归档要求" width="126">
          <template #default="{ row }">
            <el-tooltip placement="left" :show-after="120">
              <template #content>
                <div class="file-tip">
                  <div v-if="!row.archive_files.length" class="file-tip__empty">未定义需归档文件</div>
                  <div v-for="f in row.archive_files" :key="f.name" class="file-tip__row">
                    <span :class="['file-tip__mark', f.archived ? 'is-done' : '']">
                      {{ f.archived ? '✓' : '○' }}
                    </span>
                    <span class="file-tip__name">{{ f.name }}</span>
                    <span v-if="f.note" class="file-tip__note">（{{ f.note }}）</span>
                  </div>
                  <div v-if="row.archived_at" class="file-tip__meta">
                    归档完成：{{ fmtTime(row.archived_at) }} · {{ row.archived_by || '—' }}
                  </div>
                </div>
              </template>
              <span class="arch-summary">{{ archiveSummary(row) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openHistory(row)">历史</el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-text">暂无单据</div>
        </template>
      </el-table>
    </section>

    <!-- 归档勾选弹窗 -->
    <el-dialog v-model="archiveDialog.visible" :title="`归档勾选 · ${archiveDialog.row?.name || ''}`" width="520px">
      <p class="dialog-tip">
        勾选表示该文件已归档；全部勾选后单据自动记为"已归档"，并记录时间与操作人。
      </p>
      <div class="file-list">
        <div v-for="f in archiveDialog.row?.archive_files || []" :key="f.name" class="file-item">
          <el-checkbox
            :model-value="f.archived"
            :disabled="archiveDialog.saving"
            @change="toggleFile(archiveDialog.row, f)"
          >
            {{ f.name }}
          </el-checkbox>
          <span v-if="f.note" class="file-item__note">{{ f.note }}</span>
          <span v-if="f.archived" class="file-item__meta">
            {{ fmtTime(f.archived_at) }} · {{ f.archived_by || '—' }}
          </span>
        </div>
        <div v-if="!(archiveDialog.row?.archive_files || []).length" class="empty-text">
          该单据还没有定义归档文件，点下方「+ 追加文件」
        </div>
      </div>
      <template #footer>
        <el-button @click="openAddFileFromArchive">+ 追加文件</el-button>
        <el-button type="primary" @click="archiveDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 追加归档文件 -->
    <el-dialog v-model="addFileDialog.visible" title="追加归档文件" width="480px">
      <el-form label-width="88px">
        <el-form-item label="文件名称" required>
          <el-input v-model="addFileDialog.name" maxlength="60" placeholder="如：监理验收意见单" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="addFileDialog.note" maxlength="100" placeholder="选填，如：需监理签认原件" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addFileDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="addFileDialog.saving" @click="submitAddFile">追加</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 / 新增 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'create' ? '新增单据' : '编辑单据'"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form label-width="104px">
        <el-form-item label="单据名称" required>
          <el-input v-model="dialog.form.name" maxlength="60" />
        </el-form-item>
        <el-form-item label="对应管理点">
          <el-input v-model="dialog.form.cost_point" maxlength="60" />
        </el-form-item>
        <el-form-item label="用途">
          <el-input v-model="dialog.form.usage" maxlength="200" />
        </el-form-item>
        <el-form-item label="核心栏目">
          <el-input v-model="dialog.form.required_fields" type="textarea" :rows="2" maxlength="400" />
        </el-form-item>

        <!-- 审批流转节点 -->
        <el-form-item label="审批流转">
          <div class="editor">
            <div v-for="(node, index) in dialog.form.nodes" :key="index" class="editor__row">
              <span class="editor__idx">{{ index + 1 }}</span>
              <el-input v-model="dialog.form.nodes[index]" maxlength="60" placeholder="节点名称，如 造价编制" />
              <el-button link type="primary" @click="moveNode(index, -1)">上移</el-button>
              <el-button link type="danger" @click="removeNode(index)">删</el-button>
            </div>
            <el-button size="small" @click="addNode">+ 添加节点</el-button>
            <p class="editor__hint">按审批先后顺序排列；列表页可点击选择当前节点</p>
          </div>
        </el-form-item>

        <!-- 归档文件清单 -->
        <el-form-item label="归档要求">
          <div class="editor">
            <div v-for="(file, index) in dialog.form.files" :key="index" class="editor__row">
              <span class="editor__idx">{{ index + 1 }}</span>
              <el-input v-model="dialog.form.files[index].name" maxlength="60" placeholder="需要归档的文件名称" />
              <el-input v-model="dialog.form.files[index].note" maxlength="100" placeholder="备注（选填）" class="editor__note" />
              <el-button link type="danger" @click="removeFileRow(index)">删</el-button>
            </div>
            <el-button size="small" @click="addFileRow">+ 添加归档文件</el-button>
            <p class="editor__hint">这里只定义"需要归档什么"；是否已归档在列表页勾选</p>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 历史 -->
    <el-drawer v-model="history.visible" :title="`操作历史 · ${history.row?.name || ''}`" size="420px">
      <div v-loading="history.loading">
        <el-timeline v-if="history.logs.length">
          <el-timeline-item
            v-for="log in history.logs"
            :key="log.id"
            :timestamp="fmtTime(log.created_at)"
            placement="top"
          >
            <template v-if="log.kind === 'node'">
              <span class="badge badge--brand">节点</span>
              <span class="log-text">{{ log.from_value || '未开始' }} → {{ log.to_value }}</span>
            </template>
            <template v-else>
              <span class="badge badge--muted">{{ log.remark || '归档' }}</span>
              <span class="log-text">{{ log.to_value }}</span>
            </template>
            <div class="log-meta">操作人：{{ log.operator_name || '—' }}</div>
          </el-timeline-item>
        </el-timeline>
        <p v-else class="empty-text">暂无操作记录</p>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.pm-docs {
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

.toolbar {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: v.$sp-2 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.toolbar__stats {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  flex-wrap: wrap;
}

.stat {
  font-size: v.$fs-sm;
  color: v.$ink-500;

  b {
    font-family: v.$font-num;
    color: v.$ink-900;
    font-size: v.$fs-lg;
  }

  b.ok {
    color: v.$ok;
  }
}

.stat--sel {
  padding: 1px 8px;
  border-radius: 999px;
  background: v.$brand-50;
  color: v.$brand-800;
}

.toolbar__actions {
  margin-left: auto;
}

.card {
  padding: v.$sp-3;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.node-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.node-badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: v.$brand-50;
  color: v.$brand-800;
  font-size: v.$fs-xs;
  white-space: nowrap;
}

.node-pos {
  font-family: v.$font-num;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.archive-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.arch-badge {
  font-family: v.$font-num;
  font-size: v.$fs-sm;
  color: v.$ink-500;
  padding: 1px 8px;
  border-radius: 999px;
  background: v.$muted-bg;
}

.arch-badge.is-part {
  background: v.$warn-bg;
  color: v.$warn;
}

.arch-badge.is-done {
  background: v.$ok-bg;
  color: v.$ok;
}

.arch-summary {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
  font-size: v.$fs-sm;
  color: v.$ink-500;
  border-bottom: 1px dashed v.$line-strong;
  cursor: help;
}

.file-tip {
  max-width: 320px;
  font-size: v.$fs-sm;
  line-height: 1.6;
}

.file-tip__row {
  display: flex;
  gap: 4px;
  align-items: baseline;
}

.file-tip__mark {
  color: rgba(255, 255, 255, 0.6);

  &.is-done {
    color: #9be7b8;
  }
}

.file-tip__note {
  color: rgba(255, 255, 255, 0.65);
}

.file-tip__meta {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.65);
}

.file-tip__empty {
  color: rgba(255, 255, 255, 0.7);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
}

.file-item {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
  padding: 6px 0;
  border-bottom: 1px dashed v.$line-soft;
}

.file-item__note {
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.file-item__meta {
  margin-left: auto;
  font-size: v.$fs-xs;
  color: v.$ok;
  font-family: v.$font-num;
}

.dialog-tip {
  margin: 0 0 v.$sp-3;
  padding: v.$sp-2 v.$sp-3;
  background: v.$surface-sunken;
  border-radius: v.$r-sm;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.editor__row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.editor__idx {
  width: 18px;
  font-family: v.$font-num;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.editor__note {
  max-width: 200px;
}

.editor__hint {
  margin: 2px 0 0;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: v.$fs-xs;
  margin-right: 6px;
}

.badge--brand {
  background: v.$brand-50;
  color: v.$brand-800;
}

.badge--muted {
  background: v.$muted-bg;
  color: v.$muted;
}

.log-text {
  font-size: v.$fs-sm;
  color: v.$ink-700;
}

.log-meta {
  margin-top: 4px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.muted {
  color: v.$ink-400;
  font-size: v.$fs-xs;
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

  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: v.$sp-2;
  }

  .toolbar__actions {
    margin-left: 0;

    :deep(.el-button) {
      min-height: v.$touch-target;
    }
  }

  .card {
    overflow-x: auto;
  }

  .editor__row {
    flex-wrap: wrap;
  }
}
</style>
