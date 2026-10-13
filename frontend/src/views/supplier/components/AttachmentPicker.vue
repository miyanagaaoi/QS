<script setup>
/**
 * AttachmentPicker — 行附件（设计稿 03-3 展开区「行附件」/ FR-RWD-22 / TC-35）
 * ---------------------------------------------------------------------------
 * 手机端两个入口（设计稿左相机、右相册）：
 *   拍照：<input type="file" accept="image/*" capture="environment">  直接调起相机
 *   相册：<input type="file" accept="image/*">                        从相册选择（可多选）
 * 上传前本地 canvas 压缩（长边 ≤1920、质量 0.8、单张 ≤2MB，见 useImageCompress）；
 * 压缩后仍超 2MB 或非图片超 10MB（后端 settings.max_upload_size_mb）则拒绝并说明原因。
 * 接口：POST /api/supplier/attachments （multipart，字段名 file）
 *   → { filename, original_name, size, url }
 * 失败**不清空已选项**，提供「重试」；每行 ≤3 个。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { API_BASE, readToken, upload } from '@/api/request'

import { MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_LINE } from '../quoteModel'
import { isImageFile, prepareUpload } from '../composables/useImageCompress'

defineOptions({ name: 'AttachmentPicker' })

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  max: { type: Number, default: MAX_ATTACHMENTS_PER_LINE },
  /** 非图片附件的后端上限（MB） */
  maxFileMb: { type: Number, default: 10 },
  /** 无障碍用：所属行序号 */
  lineSeq: { type: [Number, String], default: '' },
})

const emit = defineEmits(['update:modelValue'])

const cameraInput = ref(null)
const albumInput = ref(null)
const uploading = ref(false)
const progress = ref(0)
const errorText = ref('')
/** 上传失败时保留的文件，点「重试」不再让用户重拍 */
const pending = ref(null)
const previewUrls = ref(new Set())

const items = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
const canAdd = computed(() => !props.disabled && items.value.length < props.max)

function isImageItem(item) {
  const name = String(item?.original_name || item?.filename || '')
  return /\.(jpe?g|png|webp|gif|bmp)$/i.test(name)
}

function extOf(item) {
  const matched = String(item?.original_name || item?.filename || '').match(/\.([0-9a-z]+)$/i)
  return matched ? matched[1].toUpperCase() : 'FILE'
}

/** 已存在的服务端附件需要带 token 拉一次 blob 才能做缩略图 */
async function ensurePreview(item) {
  if (!item || item._preview || !isImageItem(item) || !item.url) return
  const key = item.filename || item.url
  if (!key || previewUrls.value.has(key)) return
  try {
    const path = String(item.url).startsWith('/api')
      ? String(item.url).slice(4)
      : String(item.url)
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${readToken()}` },
    })
    if (!response.ok) return
    const blob = await response.blob()
    previewUrls.value.add(key)
    // 就地补预览字段：attachment 列表本身是父组件传下来的普通对象数组
    item._preview = URL.createObjectURL(blob)
  } catch {
    /* 预览失败不影响功能，回退到类型占位 */
  }
}

watch(
  () => items.value.map((item) => item?.filename).join('|'),
  () => items.value.forEach(ensurePreview),
  { immediate: true },
)

onBeforeUnmount(() => {
  items.value.forEach((item) => {
    if (item?._preview) {
      try {
        URL.revokeObjectURL(item._preview)
      } catch {
        /* 忽略 */
      }
    }
  })
})

function openCamera() {
  if (!canAdd.value) return
  errorText.value = ''
  cameraInput.value?.click()
}

function openAlbum() {
  if (!canAdd.value) return
  errorText.value = ''
  albumInput.value?.click()
}

function onPicked(event) {
  const files = Array.from(event.target?.files || [])
  event.target.value = '' // 允许重复选同一张
  if (!files.length) return
  handleFiles(files)
}

async function handleFiles(files) {
  errorText.value = ''
  const room = props.max - items.value.length
  if (room <= 0) {
    errorText.value = `每行最多 ${props.max} 个附件`
    return
  }
  const batch = files.slice(0, room)
  if (files.length > room) errorText.value = `每行最多 ${props.max} 个附件，已忽略超出的 ${files.length - room} 个`

  for (const file of batch) {
    const ok = await handleOne(file)
    if (!ok) break
  }
}

async function handleOne(file) {
  const limitBytes = props.maxFileMb * 1024 * 1024
  let prepared
  try {
    prepared = await prepareUpload(file, { maxBytes: MAX_ATTACHMENT_BYTES })
  } catch (error) {
    errorText.value = error?.message || '图片处理失败'
    return false
  }

  const isImage = isImageFile(prepared.file)
  const limit = isImage ? MAX_ATTACHMENT_BYTES : limitBytes
  if (prepared.size > limit) {
    errorText.value = isImage
      ? `压缩后仍超过 2MB（${(prepared.size / 1024 / 1024).toFixed(2)}MB），请重新拍摄或选择更小的图片`
      : `文件超过 ${props.maxFileMb}MB 上限`
    return false
  }

  return doUpload(prepared.file, { compressed: prepared.compressed, originalSize: prepared.originalSize })
}

async function doUpload(file, meta = {}) {
  uploading.value = true
  progress.value = 0
  errorText.value = ''
  pending.value = file
  try {
    const formData = new FormData()
    formData.append('file', file)
    const data = await upload('/supplier/attachments', formData, {
      onProgress: (value) => {
        progress.value = value
      },
      timeout: 60000,
      silent: true,
    })
    const item = {
      filename: data?.filename || '',
      original_name: data?.original_name || file.name,
      size: data?.size ?? file.size,
      url: data?.url || '',
    }
    if (isImageFile(file)) item._preview = URL.createObjectURL(file)
    emit('update:modelValue', [...items.value, item])
    pending.value = null
    progress.value = 0
    if (meta.compressed) {
      errorText.value = ''
    }
    return true
  } catch (error) {
    // 弱网/超时：保留本地文件，给出原因与「重试」（FR-RWD-23）
    errorText.value = error?.message || '附件上传失败'
    return false
  } finally {
    uploading.value = false
  }
}

function retry() {
  if (!pending.value) return
  doUpload(pending.value)
}

function removeAt(index) {
  if (props.disabled) return
  const next = items.value.filter((_, i) => i !== index)
  emit('update:modelValue', next)
  errorText.value = ''
}

function sizeText(item) {
  const bytes = Number(item?.size)
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}
</script>

<template>
  <div class="ap">
    <div class="ap__row">
      <div v-for="(item, index) in items" :key="item.filename || index" class="ap__thumb">
        <img
          v-if="item._preview"
          class="ap__img"
          :src="item._preview"
          :alt="item.original_name || '附件预览'"
        />
        <span v-else class="ap__file">{{ extOf(item) }}</span>
        <button
          v-if="!disabled"
          type="button"
          class="ap__del"
          :aria-label="`删除附件 ${item.original_name || index + 1}`"
          @click="removeAt(index)"
        >
          ×
        </button>
        <span class="ap__size">{{ sizeText(item) }}</span>
      </div>

      <div v-if="uploading" class="ap__ph is-loading" role="status">
        <span class="ap__pct">{{ progress }}%</span>
      </div>

      <button
        v-if="canAdd && !uploading"
        type="button"
        class="ap__ph"
        :aria-label="`第 ${lineSeq} 行：拍照上传附件`"
        @click="openCamera"
      >
        <svg width="19" height="19" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
          <path d="M2 5.5h2.2L5.4 4h5.2l1.2 1.5H14v7H2z" />
          <circle cx="8" cy="9" r="2.2" />
        </svg>
      </button>
      <button
        v-if="canAdd && !uploading"
        type="button"
        class="ap__ph is-album"
        :aria-label="`第 ${lineSeq} 行：从相册选择附件`"
        @click="openAlbum"
      >
        <svg width="19" height="19" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
          <rect x="2" y="3" width="12" height="10" rx="1.4" />
          <path d="M2 11l3.2-3 2.6 2.4L10.4 8l3.6 3.4" />
        </svg>
      </button>
    </div>

    <p class="ap__hint">支持直接拍照，单张 ≤2MB，每行最多 {{ max }} 个</p>
    <p v-if="errorText" class="ap__err">
      <span>{{ errorText }}</span>
      <button v-if="pending" type="button" class="ap__retry" @click="retry">重试上传</button>
    </p>

    <input
      ref="cameraInput"
      class="ap__file-input"
      type="file"
      accept="image/*"
      capture="environment"
      @change="onPicked"
    />
    <input
      ref="albumInput"
      class="ap__file-input"
      type="file"
      accept="image/*,application/pdf,.xlsx,.xls,.docx"
      multiple
      @change="onPicked"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.ap__row {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  align-items: center;
}

.ap__thumb {
  position: relative;
  flex: none;
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  overflow: visible;
  background: linear-gradient(135deg, #dce6e4, #c7d6d3);
  border-radius: v.$r-md;
}

.ap__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: v.$r-md;
}

.ap__file {
  font-size: 9.5px;
  font-weight: 700;
  color: #4a6663;
}

.ap__size {
  position: absolute;
  right: 0;
  bottom: -13px;
  left: 0;
  font-size: 9px;
  color: v.$ink-400;
  text-align: center;
  white-space: nowrap;
}

.ap__del {
  position: absolute;
  top: -5px;
  right: -5px;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  font-size: 11px;
  color: #fff;
  background: v.$ink-700;
  border: 2px solid #fff;
  border-radius: 50%;
  cursor: pointer;
}

.ap__ph {
  flex: none;
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  color: v.$brand-700;
  background: v.$brand-50;
  border: 1px solid v.$brand-100;
  border-radius: v.$r-md;
  cursor: pointer;

  &.is-album {
    color: v.$ink-400;
    background: v.$surface-sunken;
    border-color: v.$line;
  }

  &.is-loading {
    color: v.$brand-700;
    cursor: default;
    background: v.$brand-50;
  }
}

.ap__pct {
  font-size: 11px;
  font-weight: 700;
}

.ap__hint {
  margin: 15px 0 0;
  font-size: 11px;
  color: v.$ink-400;
}

.ap__err {
  display: flex;
  flex-wrap: wrap;
  gap: v.$sp-2;
  align-items: center;
  margin: 6px 0 0;
  font-size: 11.5px;
  color: v.$danger;
}

.ap__retry {
  min-height: 30px;
  padding: 0 10px;
  font-size: 11.5px;
  font-weight: 600;
  color: v.$danger;
  background: #fff;
  border: 1px solid v.$danger-line;
  border-radius: v.$r-md;
  cursor: pointer;
}

// 拍照/相册输入框不参与布局（点击由按钮代理）
.ap__file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
