import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { useSystemDark } from './hooks/useSystemDark'
import { router } from './router'
import { antdTheme } from './styles/theme'

/** 应用根：antd 主题对齐设计令牌（品牌色 / 圆角 / 字号 / 44px 控件），跟随系统暗色 */
export default function App() {
  const isDark = useSystemDark()

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        ...antdTheme,
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      }}
    >
      <RouterProvider router={router} />
    </ConfigProvider>
  )
}
