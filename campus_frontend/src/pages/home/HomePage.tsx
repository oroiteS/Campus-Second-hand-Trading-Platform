import { Alert, Card, Tag } from 'antd'
import { getHealth } from '../../api/system'
import { PageHeader } from '../../components/PageHeader'
import { StateView } from '../../components/StateView'
import { useAsyncData } from '../../hooks/useAsyncData'
import type { HealthData, ServiceHealth } from '../../types'
import { formatDateTime, formatLatency } from '../../utils/format'
import { EMBEDDING_MODE_TEXT } from '../../utils/statusText'
import './HomePage.css'

const SERVICE_KEYS = ['mysql', 'mongodb', 'redis', 'chroma'] as const satisfies readonly (keyof HealthData['services'])[]

const SERVICE_LABELS: Record<(typeof SERVICE_KEYS)[number], string> = {
  mysql: 'MySQL',
  mongodb: 'MongoDB',
  redis: 'Redis',
  chroma: 'Chroma',
}

function ServiceCard({ name, health }: { name: string; health: ServiceHealth }) {
  const up = health.status === 'up'
  return (
    <Card title={name} size="small" className="health-card">
      <p className="health-card__row">
        <Tag color={up ? 'success' : 'error'}>{up ? '正常' : '不可用'}</Tag>
        <span className="health-card__latency">延迟 {formatLatency(health.latency_ms)}</span>
      </p>
      {!up && health.error && (
        <p className="health-card__error" role="alert">
          {health.error}
        </p>
      )}
    </Card>
  )
}

/**
 * 首页骨架（批次 0）：/api/health 状态面板。
 * 四态齐备：加载（Skeleton + aria-busy）/ 错误（role=alert + 重试）/
 * 空（Empty）/ 正常（服务四卡 + Embedding 模式卡）；degraded 有可见提示。
 */
export function HomePage() {
  const { data, loading, error, reload } = useAsyncData(getHealth)

  return (
    <div className="page-container">
      <PageHeader
        title="校园二手交易平台"
        description="批次 0 骨架演示：平台服务健康面板（GET /api/health）"
      />

      <section className="home-section" aria-labelledby="health-heading">
        <h2 id="health-heading">服务健康</h2>
        <StateView
          loading={loading}
          error={error}
          onRetry={reload}
          empty={!data}
          emptyDescription="暂无健康数据"
        >
          {data && (
            <>
              {data.status === 'degraded' && (
                <Alert
                  className="home-health__degraded"
                  type="warning"
                  showIcon
                  role="alert"
                  message="平台处于降级模式"
                  description="部分依赖服务不可用，相关功能可能暂时受限；基础功能不受影响。"
                />
              )}
              <p className="home-health__meta">
                整体状态：
                <Tag color={data.status === 'ok' ? 'success' : 'warning'}>
                  {data.status === 'ok' ? '正常' : '降级'}
                </Tag>
                <span className="home-health__checked-at">
                  探测时间：{formatDateTime(data.checked_at)}
                </span>
              </p>
              <ul className="health-grid">
                {SERVICE_KEYS.map((key) => (
                  <li key={key}>
                    <ServiceCard name={SERVICE_LABELS[key]} health={data.services[key]} />
                  </li>
                ))}
              </ul>
              <Card
                title="Embedding 向量服务"
                size="small"
                className="health-card health-card--embedding"
              >
                <p className="health-card__row">
                  <Tag color={data.embedding.status === 'up' ? 'success' : 'error'}>
                    {data.embedding.status === 'up' ? '正常' : '不可用'}
                  </Tag>
                  {data.embedding.mode ? (
                    <Tag color="processing">{EMBEDDING_MODE_TEXT[data.embedding.mode]}</Tag>
                  ) : (
                    <Tag color="error">无可用模式</Tag>
                  )}
                </p>
                <dl className="health-card__detail">
                  <div>
                    <dt>模型</dt>
                    <dd>{data.embedding.model}</dd>
                  </div>
                  <div>
                    <dt>向量维度</dt>
                    <dd>{data.embedding.dim}</dd>
                  </div>
                </dl>
              </Card>
            </>
          )}
        </StateView>
      </section>

      <section className="home-section" aria-labelledby="intro-heading">
        <h2 id="intro-heading">平台简介</h2>
        <p className="home-intro__text">
          面向本校学生的二手交易平台：商品发布与浏览、站内聊天、订单与评价将于后续批次陆续上线。
          当前为批次 0 前端骨架，可使用右上角「演示登录态」切换 游客 / 未认证学生 / 认证学生 /
          管理员 四态，验证路由守卫拦截。
        </p>
      </section>
    </div>
  )
}
