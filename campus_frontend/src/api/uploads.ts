import type { ImageRef } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockUploadImage } from './mock/uploads'

/** POST /api/uploads：通用图片上传（multipart/form-data：file + purpose） */
export function uploadImage(file: File, purpose: 'product'): Promise<ImageRef> {
  if (USE_MOCK) {
    return mockUploadImage(file, purpose)
  }
  const formData = new FormData()
  formData.append('file', file)
  formData.append('purpose', purpose)
  return http.post<ImageRef>('/uploads', formData).then((res) => res.data)
}
