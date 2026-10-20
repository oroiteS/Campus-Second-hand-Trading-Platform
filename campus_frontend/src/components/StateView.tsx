import { Button, Empty, Skeleton } from 'antd'
import type { ReactNode } from 'react'
import './StateView.css'

interface StateViewProps {
  loading: boolean
  error: string | null
  onRetry?: () => void
  empty?: boolean
  emptyDescription?: string
  children: ReactNode
}

/**
 * 数据区块四态视图：加载 / 错误（含重试）/ 空 / 正常。
 * 错误提示 role="alert"，加载态 aria-busy，供页面统一达到四态齐备基线。
 */
export function StateView({
  loading,
  error,
  onRetry,
  empty = false,
  emptyDescription = '暂无数据',
  children,
}: StateViewProps) {
  if (loading) {
    return (
      <div className="state-view state-view--loading" role="status" aria-busy="true">
        <Skeleton active title paragraph={{ rows: 4 }} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="state-view state-view--error" role="alert">
        <p className="state-view__error-text">{error}</p>
        {onRetry && (
          <Button type="primary" onClick={onRetry}>
            重试
          </Button>
        )}
      </div>
    )
  }

  if (empty) {
    return (
      <div className="state-view state-view--empty">
        <Empty description={emptyDescription} />
      </div>
    )
  }

  return <>{children}</>
}
