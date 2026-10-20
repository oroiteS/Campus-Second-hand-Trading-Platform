import { Flex, Spin } from 'antd'
import './RouteLoading.css'

/** 路由级 Suspense fallback：带 aria-busy 的加载态 */
export function RouteLoading() {
  return (
    <Flex
      className="route-loading"
      align="center"
      justify="center"
      gap="small"
      role="status"
      aria-busy="true"
    >
      <Spin size="small" />
      <span>页面加载中…</span>
    </Flex>
  )
}
