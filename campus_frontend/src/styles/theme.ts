import type { ThemeConfig } from 'antd'

/**
 * antd 主题令牌（JS 侧唯一取值处）。
 * 与 src/styles/tokens.css 保持同步：品牌色 --color-primary、圆角 --radius-md、
 * 字号 --text-base、控件高度 --touch-target。
 */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: '#2f54eb',
    colorLink: '#2f54eb',
    borderRadius: 8,
    fontSize: 16,
    controlHeight: 44,
  },
}
