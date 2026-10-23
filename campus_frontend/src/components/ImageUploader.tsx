import { useRef, useState, type ChangeEvent } from 'react'
import { uploadImage } from '../api/uploads'
import { errorMessage, isTokenInvalidError } from '../utils/apiError'
import { UPLOAD_MAX_MB, validateUploadFile } from '../utils/validators'
import './ImageUploader.css'

/** 已上传图片（契约 ImageRef 的页面态） */
export interface UploadedImage {
  id: number
  url: string
}

interface ImageUploaderProps {
  images: UploadedImage[]
  onChange: (images: UploadedImage[]) => void
  disabled?: boolean
}

/** 图片张数上限（契约 image_ids minItems 1 / maxItems 9） */
export const MAX_PRODUCT_IMAGES = 9

/**
 * 发布/编辑共用多图上传器：
 * - 预览网格 + 删除 + 上限 9 禁加 + 张数计数（x/9，aria-live）；
 * - 客户端预检（jpg/png/webp、≤5MB）非法不发请求；上传走 api/uploads；
 * - 失败重试（保留最近一次文件）；「上传序即展示序」文案说明；
 * - 拖拽排序不做（YAGNI，删除重传即可）。
 */
export function ImageUploader({ images, onChange, disabled = false }: ImageUploaderProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retryFile, setRetryFile] = useState<File | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const atLimit = images.length >= MAX_PRODUCT_IMAGES
  const lockAll = disabled || uploading

  async function upload(file: File): Promise<void> {
    setUploading(true)
    setError(null)
    try {
      const imageRef = await uploadImage(file, 'product')
      onChange([...images, { id: imageRef.id, url: imageRef.url }])
      setRetryFile(null)
    } catch (err) {
      if (!isTokenInvalidError(err)) {
        setError(errorMessage(err, '图片上传失败，请重试'))
      }
    } finally {
      setUploading(false)
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0] ?? null
    event.target.value = ''
    if (!file) return
    // 客户端预检：类型/大小非法仅提示，不发请求
    const invalid = validateUploadFile(file, '图片')
    if (invalid) {
      setRetryFile(null)
      setError(invalid)
      return
    }
    if (atLimit) {
      setRetryFile(null)
      setError(`最多上传 ${MAX_PRODUCT_IMAGES} 张图片`)
      return
    }
    setRetryFile(file)
    void upload(file)
  }

  function handleRemove(id: number): void {
    onChange(images.filter((image) => image.id !== id))
  }

  return (
    <div className="image-uploader">
      {images.length > 0 && (
        <ul className="image-uploader__grid" aria-label="已上传图片列表（序号即展示顺序）">
          {images.map((image, index) => (
            <li key={image.id} className="image-uploader__item">
              <img
                src={image.url}
                alt={`商品图 ${index + 1}`}
                loading="lazy"
                decoding="async"
              />
              <span className="image-uploader__order" aria-hidden="true">
                {index + 1}
              </span>
              <button
                type="button"
                className="image-uploader__remove"
                aria-label={`删除第 ${index + 1} 张图片`}
                onClick={() => handleRemove(image.id)}
                disabled={lockAll}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="image-uploader__actions">
        <button
          type="button"
          className="image-uploader__add"
          onClick={() => inputRef.current?.click()}
          disabled={lockAll || atLimit}
          aria-describedby="image-uploader-hint"
        >
          {uploading ? '上传中…' : atLimit ? `已达上限 ${MAX_PRODUCT_IMAGES} 张` : '添加图片'}
        </button>
        <span className="image-uploader__count" aria-live="polite">
          {images.length}/{MAX_PRODUCT_IMAGES}
        </span>
        <input
          ref={inputRef}
          id="image-uploader-input"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="image-uploader__input"
          onChange={handleFileChange}
          disabled={lockAll || atLimit}
          aria-label="选择商品图片文件（jpg/png/webp，不超过 5MB）"
        />
      </div>

      <p id="image-uploader-hint" className="form-field__hint">
        支持 jpg / png / webp，单张不超过 {UPLOAD_MAX_MB} MB；上传顺序即展示顺序
        （首图为封面），需调整顺序可删除后重新上传。
      </p>

      {error && (
        <p className="form-field__error image-uploader__error" role="alert">
          {error}
          {retryFile && !uploading && (
            <button
              type="button"
              className="image-uploader__retry"
              onClick={() => void upload(retryFile)}
            >
              重试
            </button>
          )}
        </p>
      )}
    </div>
  )
}
