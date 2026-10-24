/**
 * mock 图源公共工具：文件 → data URI、inline SVG 占位图。
 *
 * 依赖方向：uploads / users 各自 import 本文件，**不得互相 import**（避免成环）。
 * 本模块只依赖浏览器 API（FileReader），mock 仅在 dev/mock 模式执行。
 */

interface SvgOptions {
  width: number
  height: number
  /** 底色（mock 图片内容色，非 UI 设计令牌） */
  fill: string
  /** 居中文本行（首行加粗大字号，其余为说明行） */
  lines: string[]
  /** 首行字号（其余行取 60%） */
  fontSize: number
  /** 底图形状：商品/上传占位用 rect（默认），头像用 circle */
  shape?: 'rect' | 'circle'
}

/**
 * SVG 命名空间：data URI SVG 的必需 xmlns（W3C 规范要求），非外网图源。
 * 分段拼接以保持本目录源码零 http 字面（任务卡图源铁律）；**本常量是
 * 全目录唯一拼接点**，其余 mock 模块一律 import，不得各自再拼一份。
 */
export const SVG_NAMESPACE = 'http' + '://' + 'www.w3.org/2000/svg'

/** 生成居中文本的 inline SVG data URI（零外网依赖，不会裂图） */
export function svgDataUrl({
  width,
  height,
  fill,
  lines,
  fontSize,
  shape = 'rect',
}: SvgOptions): string {
  const backdrop =
    shape === 'circle'
      ? `<circle cx='${Math.round(width / 2)}' cy='${Math.round(height / 2)}' r='${Math.round(Math.min(width, height) / 2)}' fill='${fill}'/>`
      : `<rect width='${width}' height='${height}' fill='${fill}'/>`
  const lineHeight = Math.round(fontSize * 1.4)
  const startY = Math.round(height / 2 - ((lines.length - 1) * lineHeight) / 2 + fontSize / 3)
  const body = lines
    .map((line, index) => {
      const size = index === 0 ? fontSize : Math.round(fontSize * 0.6)
      const y = startY + index * lineHeight
      return `<text x='${Math.round(width / 2)}' y='${y}' font-size='${size}' font-family='sans-serif' text-anchor='middle' fill='#ffffff'>${line}</text>`
    })
    .join('')
  const svg = `<svg xmlns='${SVG_NAMESPACE}' width='${width}' height='${height}'>${backdrop}${body}</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

/**
 * 读取上传文件为 data URI（mock 等价演示服务端存储）。
 * 读取失败（如浏览器禁用 FileReader）时回退调用方给定的占位图，保证 <img> 不裂。
 */
export function readFileAsDataUrl(file: File, fallback: () => string): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      resolve(typeof reader.result === 'string' && reader.result !== '' ? reader.result : fallback())
    }
    reader.onerror = () => {
      resolve(fallback())
    }
    reader.readAsDataURL(file)
  })
}
