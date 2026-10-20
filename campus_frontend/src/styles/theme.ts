import type { ThemeConfig } from 'antd'

/**
 * 品牌色常量（TS 侧取值处）：antd token 需具体色值计算衍生色，无法消费 CSS 变量，
 * 故在此镜像 src/styles/tokens.css 的 --color-primary——
 * 亮色对应 :root 的 #2f54eb，暗色对应 prefers-color-scheme: dark 的 #7c8ff5。
 * 同步义务：任一处改动时必须同步另一处。
 */
const BRAND_COLOR_LIGHT = '#2f54eb'
const BRAND_COLOR_DARK = '#7c8ff5'

/**
 * antd 主题令牌（JS 侧唯一取值处），按 isDark 返回与 tokens.css 同名的品牌色。
 * 其余与 tokens.css 保持同步：圆角 --radius-md、字号 --text-base、控件高度 --touch-target。
 */
export function createAntdTheme(isDark: boolean): ThemeConfig {
  const brand = isDark ? BRAND_COLOR_DARK : BRAND_COLOR_LIGHT
  return {
    token: {
      colorPrimary: brand,
      colorLink: brand,
      borderRadius: 8,
      fontSize: 16,
      controlHeight: 44,
    },
  }
}
