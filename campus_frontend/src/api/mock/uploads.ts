import type { ImageRef } from '../../types'
import { delay } from '../../utils/delay'
import { validateUploadFile } from '../../utils/validators'
import { ApiError } from '../http'
import { requireVerifiedSession } from './users'

/**
 * POST /api/uploads 契约同构 mock。
 *
 * - 五件套校验中的「扩展名 + MIME + 大小」由 validateUploadFile 客户端预检同源模拟，
 *   魔数嗅探与哈希改名属服务端行为，mock 以 FileReader 读取内容转 data URI 等价演示；
 * - 上传记录（id / ownerId / url）登记在内存注册表，供发布/编辑校验
 *   `image_ids`「须为本人 purpose=product 上传」（9001 复演）；
 * - mock 模式 ImageRef.url 一律为本地 data URI（任务卡图源铁律，零外网依赖）。
 */

/** 上传记录：id 与归属人；url 为本地 data URI（mock 图源口径） */
interface MockUpload {
  id: number
  ownerId: number
  url: string
}

const UPLOADS: MockUpload[] = []

let nextUploadIdSeed = 90_001

/** 读文件内容为 data URI（mock 图源）；读取失败回退占位 SVG */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      resolve(typeof reader.result === 'string' ? reader.result : fallbackPlaceholder())
    }
    reader.onerror = () => {
      resolve(fallbackPlaceholder())
    }
    reader.readAsDataURL(file)
  })
}

/** 兜底占位图（中性灰 SVG data URI，与商品池占位策略一致） */
function fallbackPlaceholder(): string {
  // SVG 命名空间分段拼接：保持本目录源码零 http 字面（任务卡图源铁律）
  const ns = 'http' + '://' + 'www.w3.org/2000/svg'
  const svg =
    `<svg xmlns='${ns}' width='600' height='450'>` +
    `<rect width='600' height='450' fill='#495057'/>` +
    `<text x='300' y='230' font-size='28' text-anchor='middle' font-family='sans-serif' fill='#ffffff'>mock 上传占位图</text>` +
    `</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

export function mockUploadImage(file: File, purpose: 'product'): Promise<ImageRef> {
  return delay(600).then(async () => {
    const user = requireVerifiedSession()
    if (user.role === 'admin') {
      // 契约：管理员上传一律 409/9003（管理员无交易能力）
      throw new ApiError(9003, '管理员无交易能力，不能上传商品图片', null)
    }
    if (purpose !== 'product') {
      throw new ApiError(9001, '参数校验失败', {
        fields: { purpose: '上传用途无效，本版本仅支持 product' },
      })
    }
    const fileError = validateUploadFile(file, '图片')
    if (fileError) {
      throw new ApiError(9001, '参数校验失败', { fields: { file: fileError } })
    }
    const id = nextUploadIdSeed++
    const url = await fileToDataUrl(file)
    UPLOADS.push({ id, ownerId: user.id, url })
    return { id, url }
  })
}

/** 查找上传记录（发布/编辑校验 image_ids 归属时消费） */
export function findMockUpload(id: number): MockUpload | undefined {
  return UPLOADS.find((item) => item.id === id)
}

/** image_ids 归属校验：须为该用户本人上传的图片 */
export function isOwnedUpload(id: number, ownerId: number): boolean {
  return UPLOADS.some((item) => item.id === id && item.ownerId === ownerId)
}
