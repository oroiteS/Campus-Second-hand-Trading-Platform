import './DegradedBanner.css'

interface DegradedBannerProps {
  /** 契约 degraded_reason；缺省时展示通用文案 */
  reason?: string
}

/**
 * 降级提示条（契约消费纪律第 5 条：data.degraded = true 时用户可见，
 * 不阻断页面可用）。role="status"：降级是状态信息而非紧急告警。
 */
export function DegradedBanner({ reason }: DegradedBannerProps) {
  return (
    <div className="degraded-banner" role="status">
      <span className="degraded-banner__icon" aria-hidden="true">
        ⚠
      </span>
      <p className="degraded-banner__text">
        部分服务暂不可用，已切换降级模式
        {reason ? `（${reason}）` : ''}
        ，结果可能不如平时精准。
      </p>
    </div>
  )
}
