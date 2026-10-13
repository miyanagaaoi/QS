<script setup>
/**
 * SupplierImport — 供货商账号批量导入弹窗（PRD 5.4.2 / FR-ACC-10~13，设计稿 04-2 弹窗）
 * ---------------------------------------------------------------------------
 * 流程：下载模板 → 选择 .xlsx → 预校验（不落库）→ 行级错误报告 → 确认导入 → 结果报告
 *
 * 后端契约（实测）：
 *   POST /admin/supplier-accounts/import          multipart 字段名 file，仅 .xlsx
 *     → data = { total, valid, invalid, errors:[{ row, column, value, reason }], token }
 *        total   = 模板中的数据行数
 *        valid   = 可通过的行数
 *        invalid = 校验失败的行数（**按行计**；errors 是错误条目，同一行可能多条）
 *        row     = Excel 中的实际行号（表头为第 1 行，数据从第 2 行开始）
 *        column  = 中文列名（供货商名称 / 登录账号 / 初始密码 / 联系电话 / 邮箱 / 地址）
 *        value   = 出错单元格的值，可能为 null
 *   POST /admin/supplier-accounts/import/confirm  { token }
 *     → data = { success, failed, errors:[{ row, column(null), value(登录账号), reason }] }
 *     token 单次有效，重复提交返回 40001"导入凭证无效或已使用，请重新上传文件预校验"
 *   POST /admin/supplier-accounts/import/error-report  multipart file → xlsx 错误报告（不落库）
 *
 * 设计稿里的错误表列（行号/供货商名称/登录账号/失败原因）后端并不返回行级业务字段，
 * 因此这里按后端真实字段渲染为「行号 / 列名 / 当前值 / 失败原因」——
 * 同一行的列名 + 值即可定位到具体单元格，信息量不小于设计稿且不会有编造数据。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useBreakpoint } from '@/composables/useBreakpoint'
import { formatFileSize } from '@/composables/useFormat'

import * as api from './adminApi'

defineOptions({ name: 'SupplierImport' })

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'imported'])

const { isMobile } = useBreakpoint()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

/** step: select 选择文件 → preview 预校验结果 → done 导入结果 */
const step = ref('select')
const file = ref(null)
const uploadRef = ref(null)
const uploading = ref(false)
const progress = ref(0)
const submitting = ref(false)
const exporting = ref(false)

const preview = reactive({ total: 0, valid: 0, invalid: 0, errors: [], token: '', message: '' })
const result = reactive({ success: 0, failed: 0, errors: [] })

const errorCount = computed(() => preview.errors.length)

const ERROR_COLUMNS = [
  { key: 'row', label: 'Excel 行号' },
  { key: 'column', label: '列名' },
  { key: 'value', label: '当前值' },
  { key: 'reason', label: '失败原因' },
]

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  },
)

function reset() {
  step.value = 'select'
  file.value = null
  progress.value = 0
  uploading.value = false
  submitting.value = false
  Object.assign(preview, { total: 0, valid: 0, invalid: 0, errors: [], token: '', message: '' })
  Object.assign(result, { success: 0, failed: 0, errors: [] })
  uploadRef.value?.clearFiles?.()
}

function close() {
  visible.value = false
}

// ---------------------------------------------------------------------------
// 下载模板
// ---------------------------------------------------------------------------
async function downloadTemplate() {
  try {
    const { filename } = await api.downloadImportTemplate()
    ElMessage.success(
      isMobile.value
        ? '模板已开始下载，建议在电脑上填写'
        : `模板已下载（${filename}），请按模板列填写后上传`,
    )
  } catch {
    /* request.js 已提示原因 */
  }
}

// ---------------------------------------------------------------------------
// 选择文件 → 预校验
// ---------------------------------------------------------------------------
function onFileChange(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return

  if (!/\.xlsx$/i.test(raw.name || '')) {
    ElMessage.error(
      /\.xls$/i.test(raw.name || '')
        ? '仅支持 .xlsx，请先用 Excel 将 .xls 另存为 .xlsx'
        : '仅支持 .xlsx 格式的模板文件',
    )
    uploadRef.value?.clearFiles?.()
    return
  }
  if (raw.size > api.MAX_IMPORT_BYTES) {
    ElMessage.error(`文件超过 ${Math.round(api.MAX_IMPORT_BYTES / 1024 / 1024)}MB 限制`)
    uploadRef.value?.clearFiles?.()
    return
  }

  file.value = raw
  runPreview()
}

async function runPreview() {
  if (!file.value) return
  uploading.value = true
  progress.value = 0
  try {
    const data = await api.previewImport(file.value, (value) => {
      progress.value = value
    })
    Object.assign(preview, {
      total: Number(data?.total || 0),
      valid: Number(data?.valid || 0),
      invalid: Number(data?.invalid || 0),
      errors: Array.isArray(data?.errors) ? data.errors : [],
      token: data?.token || '',
      message: '',
    })
    step.value = 'preview'
  } catch (error) {
    // 表头缺列 / 文件解析失败 / 无数据行等由后端给出原文原因
    preview.message = String(error?.message || '预校验失败，请检查文件后重试')
    step.value = 'select'
    ElMessage.error(preview.message)
  } finally {
    uploading.value = false
  }
}

function reselect() {
  uploadRef.value?.clearFiles?.()
  file.value = null
  step.value = 'select'
  progress.value = 0
}

// ---------------------------------------------------------------------------
// 导出错误报告（后端需要重新上传同一文件）
// ---------------------------------------------------------------------------
async function exportErrors() {
  // 导出错误报告需要把**原始文件**重新上传给后端解析（后端不落库、不签发 token），
  // 因此没有文件时必须明确提示，不能静默无反应。
  if (!file.value) {
    ElMessage.warning('导出错误报告需要原始文件，请重新选择 .xlsx 文件后再试')
    return
  }
  exporting.value = true
  try {
    await api.exportImportErrorReport(file.value)
    ElMessage.success('错误报告已下载，可在 Excel 中修正后重新上传')
  } catch {
    /* request.js 已提示原因 */
  } finally {
    exporting.value = false
  }
}

// ---------------------------------------------------------------------------
// 确认导入
// ---------------------------------------------------------------------------
async function confirm(all = false) {
  if (!preview.token) {
    ElMessage.error('导入凭证已失效，请重新上传文件预校验')
    return
  }
  if (all && preview.invalid > 0) {
    try {
      await ElMessageBox.confirm(
        `本次将导入校验通过的 ${preview.valid} 行，校验失败的 ${preview.invalid} 行会被跳过。` +
          '失败行可按错误报告修正后再次上传。',
        `仅导入通过的 ${preview.valid} 行？`,
        { type: 'warning', confirmButtonText: `导入 ${preview.valid} 行`, cancelButtonText: '再检查一下' },
      )
    } catch {
      return
    }
  }

  submitting.value = true
  try {
    const data = await api.confirmImport(preview.token)
    Object.assign(result, {
      success: Number(data?.success || 0),
      failed: Number(data?.failed || 0),
      errors: Array.isArray(data?.errors) ? data.errors : [],
    })
    step.value = 'done'
    ElMessage.success(`导入完成：成功 ${result.success} 条，失败 ${result.failed} 条`)
    emit('imported', { ...result })
  } catch (error) {
    // token 单次有效：重复点击 / 超时后后端返回 40001
    preview.token = ''
    step.value = 'select'
    file.value = null
    ElMessage.error(String(error?.message || '导入失败，请重新上传文件预校验'))
  } finally {
    submitting.value = false
  }
}

function cellText(value) {
  if (value === null || value === undefined || value === '') return '（空）'
  return String(value)
}

function isBlank(value) {
  return value === null || value === undefined || value === ''
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="step === 'done' ? '批量导入结果' : '批量导入供货商账号'"
    :width="isMobile ? '94%' : '880px'"
    :close-on-click-modal="false"
    class="import-dialog"
  >
    <!-- ==================== 1. 选择文件 ==================== -->
    <template v-if="step === 'select'">
      <div class="sys-alert sys-alert--info">
        <span class="sys-alert__icon">i</span>
        <div>
          <b>请使用「下载导入模板」生成的模板。</b>
          模板列：供货商名称、联系人、联系电话、邮箱、地址、登录账号、初始密码。
          表头不要改动，否则预校验会直接报缺列。
        </div>
      </div>

      <el-upload
        ref="uploadRef"
        class="up"
        drag
        action="#"
        accept=".xlsx"
        :auto-upload="false"
        :show-file-list="false"
        :limit="1"
        :disabled="uploading"
        @change="onFileChange"
      >
        <div class="up__icon">↑</div>
        <div class="up__title">把 .xlsx 文件拖到这里，或<em>点击选择文件</em></div>
        <div class="up__hint">
          仅支持 .xlsx（.xls 请先另存为 .xlsx）· 单次最多 2000 行 · 不超过
          {{ Math.round(api.MAX_IMPORT_BYTES / 1024 / 1024) }}MB
        </div>
      </el-upload>

      <el-progress
        v-if="uploading"
        class="up__progress"
        :percentage="progress"
        :stroke-width="6"
        :text-inside="true"
      />

      <div v-if="preview.message" class="sys-alert sys-alert--danger">
        <span class="sys-alert__icon">!</span>
        <div><b>文件预校验未通过：</b>{{ preview.message }}</div>
      </div>
    </template>

    <!-- ==================== 2. 预校验结果 ==================== -->
    <template v-else-if="step === 'preview'">
      <div class="up-file">
        <div class="up-file__main">
          <b class="up-file__name">{{ file?.name }}</b>
          <div class="sys-sub">
            {{ formatFileSize(file?.size) }} · 已预校验，<b>尚未写入数据库</b>
          </div>
        </div>
        <el-button size="small" @click="reselect">重新选择文件</el-button>
      </div>

      <div class="sys-stat">
        <div class="sys-stat__item sys-stat__item--ok">
          <div class="sys-stat__k">校验通过</div>
          <div class="sys-stat__v">{{ preview.valid }}</div>
        </div>
        <div class="sys-stat__item sys-stat__item--err">
          <div class="sys-stat__k">校验失败（行）</div>
          <div class="sys-stat__v">{{ preview.invalid }}</div>
        </div>
        <div class="sys-stat__item sys-stat__item--skip">
          <div class="sys-stat__k">模板数据行合计</div>
          <div class="sys-stat__v">{{ preview.total }}</div>
        </div>
      </div>

      <div v-if="preview.invalid > 0" class="sys-alert sys-alert--danger">
        <span class="sys-alert__icon">!</span>
        <div>
          <b>{{ preview.invalid }} 行数据存在问题（共 {{ errorCount }} 处错误），无法导入。</b>
          可先导出错误报告，修正后重新上传；也可选择「仅导入通过的 {{ preview.valid }} 行」。
        </div>
      </div>
      <div v-else class="sys-alert sys-alert--ok">
        <span class="sys-alert__icon">✓</span>
        <div>
          <b>全部 {{ preview.total }} 行校验通过，可以导入。</b>
          导入后账号状态为"启用"，初始密码为模板中填写的值。
        </div>
      </div>

      <!-- 行级错误报告：行号 / 列名 / 当前值 / 失败原因（桌面表格） -->
      <template v-if="errorCount">
        <div class="imp-block__head">
          <b>错误明细</b>
          <span class="sys-sub">
            行号 = Excel 中的实际行号（表头为第 1 行）· 同一行可能有多处错误
          </span>
        </div>

        <div v-if="!isMobile" class="sys-scroll-x imp-errors">
          <table class="sys-table">
            <thead>
              <tr>
                <th v-for="col in ERROR_COLUMNS" :key="col.key" :style="{ width: col.key === 'reason' ? undefined : '150px' }">
                  {{ col.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in preview.errors" :key="`${item.row}-${item.column}-${index}`">
                <td class="sys-num">第 {{ item.row }} 行</td>
                <td>{{ item.column || '—' }}</td>
                <td>
                  <span v-if="isBlank(item.value)" class="sys-sub">（空）</span>
                  <span v-else class="sys-num">{{ item.value }}</span>
                </td>
                <td class="imp-errors__reason">{{ item.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 手机端：错误条目转卡片 -->
        <ul v-else class="imp-errors-cards">
          <li v-for="(item, index) in preview.errors" :key="`m-${item.row}-${item.column}-${index}`" class="imp-err-card">
            <div class="imp-err-card__head">
              <span class="sys-num">第 {{ item.row }} 行</span>
              <span class="imp-err-card__col">{{ item.column || '—' }}</span>
            </div>
            <div class="imp-err-card__val">
              当前值：<span v-if="isBlank(item.value)" class="sys-sub">（空）</span>
              <span v-else class="sys-num">{{ item.value }}</span>
            </div>
            <div class="imp-err-card__reason">{{ item.reason }}</div>
          </li>
        </ul>
      </template>

      <div class="sys-alert sys-alert--info">
        <span class="sys-alert__icon">i</span>
        <div>
          <b>导入后规则：</b>所有新账号的密码为模板中填写的初始密码，账号状态为"启用"，
          <b>本批次不强制首次登录修改密码</b>（如需强制，可在列表里对该账号执行「重置密码」）；
          供货商名称不存在时会自动创建供货商档案。
        </div>
      </div>
    </template>

    <!-- ==================== 3. 导入结果 ==================== -->
    <template v-else>
      <div class="sys-stat">
        <div class="sys-stat__item sys-stat__item--ok">
          <div class="sys-stat__k">导入成功</div>
          <div class="sys-stat__v">{{ result.success }}</div>
        </div>
        <div class="sys-stat__item" :class="result.failed ? 'sys-stat__item--err' : 'sys-stat__item--skip'">
          <div class="sys-stat__k">导入失败</div>
          <div class="sys-stat__v">{{ result.failed }}</div>
        </div>
      </div>

      <div v-if="result.failed" class="sys-alert sys-alert--danger">
        <span class="sys-alert__icon">!</span>
        <div>
          <b>{{ result.failed }} 条写入失败。</b>
          常见原因是确认导入期间该登录账号或供货商档案已被其他操作占用；可按下方明细修正后重新上传。
        </div>
      </div>
      <div v-else class="sys-alert sys-alert--ok">
        <span class="sys-alert__icon">✓</span>
        <div><b>{{ result.success }} 条供货商账号已创建并启用。</b>请把初始密码线下告知对应供货商。</div>
      </div>

      <template v-if="result.errors.length">
        <div class="imp-block__head"><b>失败明细</b></div>
        <div class="sys-scroll-x imp-errors">
          <table class="sys-table">
            <thead>
              <tr>
                <th style="width: 150px">Excel 行号</th>
                <th style="width: 200px">登录账号</th>
                <th>失败原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in result.errors" :key="`r-${index}`">
                <td class="sys-num">第 {{ item.row }} 行</td>
                <td class="sys-num">{{ cellText(item.value) }}</td>
                <td class="imp-errors__reason">{{ item.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <div class="sys-alert sys-alert--info">
        <span class="sys-alert__icon">i</span>
        <div>
          <b>导入后规则：</b>初始密码为模板中填写的密码（8~20 位、至少含字母与数字）；
          <b>本批次不强制供货商首次登录修改密码</b>（如需强制，可在列表里对该账号执行「重置密码」）；
          名称不存在时已自动创建供货商档案（一个档案只绑定一个账号）。
        </div>
      </div>
    </template>

    <template #footer>
      <!-- 选择文件 -->
      <template v-if="step === 'select'">
        <el-button class="imp-btn" @click="downloadTemplate">下载导入模板</el-button>
        <el-button class="imp-btn" @click="close">取消</el-button>
      </template>

      <!-- 预校验结果 -->
      <template v-else-if="step === 'preview'">
        <el-button class="imp-btn" @click="close">取消</el-button>
        <el-button
          class="imp-btn"
          :disabled="!errorCount || !file"
          :loading="exporting"
          @click="exportErrors"
        >
          导出错误报告
        </el-button>
        <el-button
          v-if="preview.invalid > 0"
          class="imp-btn"
          type="primary"
          :loading="submitting"
          @click="confirm(true)"
        >
          仅导入通过的 {{ preview.valid }} 行
        </el-button>
        <el-button
          v-else
          class="imp-btn"
          type="primary"
          :loading="submitting"
          @click="confirm(false)"
        >
          确认导入 {{ preview.valid }} 行
        </el-button>
      </template>

      <!-- 导入结果 -->
      <template v-else>
        <el-button class="imp-btn" @click="close">完成</el-button>
        <el-button class="imp-btn" type="primary" @click="reset">继续导入</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
@use './system-shared';
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

// —— 上传区（设计稿 .upload）——
.up {
  display: block;

  :deep(.el-upload) {
    display: block;
    width: 100%;
  }

  :deep(.el-upload-dragger) {
    padding: v.$sp-5 v.$sp-4;
    background: v.$surface-sunken;
    border: 1.5px dashed v.$line-strong;
    border-radius: v.$r-md;

    &:hover {
      border-color: v.$brand-600;
      background: v.$brand-50;
    }
  }
}

.up__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin: 0 auto v.$sp-2;
  font-size: 18px;
  font-weight: 700;
  color: v.$brand-700;
  background: v.$brand-50;
  border: 1px solid v.$brand-100;
  border-radius: v.$r-md;
}

.up__title {
  font-size: v.$fs-lg;
  font-weight: 600;
  color: v.$ink-900;

  em {
    font-style: normal;
    color: v.$brand-700;
  }
}

.up__hint {
  margin-top: 5px;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.up__progress {
  margin-top: v.$sp-3;
}

// —— 已选文件条 ——
.up-file {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: 11px v.$sp-3;
  margin-bottom: v.$sp-3;
  background: v.$surface-sunken;
  border: 1px solid v.$line;
  border-radius: v.$r-md;
}

.up-file__main {
  flex: 1;
  min-width: 0;
}

.up-file__name {
  display: block;
  font-size: v.$fs-body;
  font-weight: 600;
  word-break: break-all;
}

// —— 错误明细 ——
.imp-block__head {
  display: flex;
  align-items: baseline;
  gap: v.$sp-2;
  flex-wrap: wrap;
  margin-bottom: v.$sp-2;

  b {
    font-size: v.$fs-lg;
  }
}

.imp-errors {
  max-height: 320px;
  margin-bottom: v.$sp-3;
  border: 1px solid v.$line;
  border-radius: v.$r-md;

  .imp-errors__reason {
    color: v.$danger;
  }
}

.imp-errors-cards {
  display: flex;
  flex-direction: column;
  gap: v.$sp-2;
  margin-bottom: v.$sp-3;
}

.imp-err-card {
  padding: v.$sp-3;
  background: v.$danger-bg;
  border: 1px solid v.$danger-line;
  border-radius: v.$r-md;
}

.imp-err-card__head {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  font-weight: 600;
  color: #8e1b12;
}

.imp-err-card__col {
  font-size: v.$fs-xs;
  font-weight: 600;
  padding: 0 6px;
  background: v.$surface;
  border: 1px solid v.$danger-line;
  border-radius: v.$r-sm;
}

.imp-err-card__val {
  margin-top: 5px;
  font-size: v.$fs-sm;
  color: v.$ink-700;
  word-break: break-word;
}

.imp-err-card__reason {
  margin-top: 4px;
  font-size: v.$fs-sm;
  color: v.$danger;
  word-break: break-word;
}

// 弹窗底部按钮：手机端 ≥44px 热区（FR-RWD-06）
.imp-btn {
  @include bp.mobile {
    min-height: v.$touch-target;
    margin: 0 0 v.$sp-2 v.$sp-2;
  }
}

@include bp.mobile {
  :global(.import-dialog .el-dialog__footer) {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
}
</style>
