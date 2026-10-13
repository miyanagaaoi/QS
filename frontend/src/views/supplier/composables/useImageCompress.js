/**
 * 附件图片压缩（FR-RWD-22 / PRD 10.5）
 * ---------------------------------------------------------------------------
 * 目标：拍照后**上传前**在本地压缩到 长边 ≤1920px、JPEG 质量 0.8、单张 ≤2MB。
 * 实现要点：
 *  1. 用 <img> + objectURL 解码，不用 createImageBitmap（iOS Safari 兼容性更稳）；
 *  2. 现代浏览器在解码时已按 EXIF orientation 应用方向（CSS image-orientation 默认
 *     from-image），因此 canvas 绘制出来就是正向；极端机型的 EXIF 旋转仍需真机确认
 *     （PRD 10.6 第 5 条）；
 *  3. 压完仍 >2MB 时逐档降质量再试，最后再等比缩小，最多 4 轮，避免死在超大图；
 *  4. 非图片文件（pdf/xlsx/docx）不做压缩，仅做尺寸校验（交由调用方）。
 */

export const IMAGE_MAX_EDGE = 1920
export const IMAGE_QUALITY = 0.8
export const IMAGE_MAX_BYTES = 2 * 1024 * 1024

export function isImageFile(file) {
  if (!file) return false
  if (String(file.type || '').startsWith('image/')) return true
  return /\.(jpe?g|png|webp|heic|heif|bmp|gif)$/i.test(file.name || '')
}

function replaceExt(name, ext) {
  const base = String(name || 'photo').replace(/\.[^./\\]+$/, '')
  return `${base || 'photo'}${ext}`
}

function loadImage(objectUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片解码失败，请重新拍照或换一张图片'))
    img.src = objectUrl
  })
}

function canvasToBlob(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('图片压缩失败'))),
      'image/jpeg',
      quality,
    )
  })
}

/**
 * 压缩一张图片。
 * @param {File|Blob} file 原始文件（相机/相册）
 * @param {{maxEdge?: number, quality?: number, maxBytes?: number}} options
 * @returns {Promise<{file: File, width: number, height: number, originalSize: number, size: number, compressed: boolean}>}
 */
export async function compressImage(file, options = {}) {
  const maxEdge = options.maxEdge || IMAGE_MAX_EDGE
  const baseQuality = options.quality || IMAGE_QUALITY
  const maxBytes = options.maxBytes || IMAGE_MAX_BYTES
  const originalSize = Number(file?.size || 0)
  const sourceUrl = URL.createObjectURL(file)

  try {
    const img = await loadImage(sourceUrl)
    const naturalW = img.naturalWidth || img.width || 0
    const naturalH = img.naturalHeight || img.height || 0
    if (!naturalW || !naturalH) throw new Error('无法读取图片尺寸')

    // 等比缩放到长边上限
    const scale = Math.min(1, maxEdge / Math.max(naturalW, naturalH))
    let width = Math.max(1, Math.round(naturalW * scale))
    let height = Math.max(1, Math.round(naturalH * scale))

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('当前浏览器不支持图片压缩')

    const attempts = [
      { width, height, quality: baseQuality },
      { width, height, quality: 0.68 },
      { width, height, quality: 0.55 },
      { width: Math.round(width * 0.7), height: Math.round(height * 0.7), quality: 0.6 },
      { width: Math.round(width * 0.5), height: Math.round(height * 0.5), quality: 0.55 },
    ]

    let blob = null
    let used = attempts[0]
    for (const attempt of attempts) {
      canvas.width = Math.max(1, attempt.width)
      canvas.height = Math.max(1, attempt.height)
      ctx.fillStyle = '#FFFFFF' // PNG/HEIC 转 JPEG 时先铺白底，避免透明区域变黑
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      blob = await canvasToBlob(canvas, attempt.quality)
      used = attempt
      if (blob.size <= maxBytes) break
    }

    if (!blob) throw new Error('图片压缩失败')
    width = used.width
    height = used.height

    const outFile = new File([blob], replaceExt(file.name, '.jpg'), {
      type: 'image/jpeg',
      lastModified: Date.now(),
    })
    return {
      file: outFile,
      width,
      height,
      originalSize,
      size: blob.size,
      compressed: originalSize > blob.size,
    }
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

/**
 * 按需要压缩：图片走压缩，其他类型原样返回。
 * @returns {Promise<{file: File|Blob, size: number, compressed: boolean, originalSize: number}>}
 */
export async function prepareUpload(file, options = {}) {
  if (!isImageFile(file)) {
    return {
      file,
      size: Number(file?.size || 0),
      compressed: false,
      originalSize: Number(file?.size || 0),
    }
  }
  return compressImage(file, options)
}

export default { compressImage, prepareUpload, isImageFile, IMAGE_MAX_EDGE, IMAGE_QUALITY, IMAGE_MAX_BYTES }
