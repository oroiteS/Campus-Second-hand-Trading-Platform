import dayjs from 'dayjs'
import { delay } from '../../utils/delay'
import type { components } from '../types'

type HealthData = components['schemas']['HealthData']

/**
 * /api/health 契约同构 mock。
 * 结构与 openapi.yaml HealthData 一字不差；chroma 置为 down，
 * 整体 status = degraded，用于演示降级态的可见提示。
 */
export function mockGetHealth(): Promise<HealthData> {
  return delay(400).then(() => {
    const data: HealthData = {
      status: 'degraded',
      checked_at: dayjs().format('YYYY-MM-DDTHH:mm:ssZ'),
      services: {
        mysql: { status: 'up', latency_ms: 3, error: null },
        mongodb: { status: 'up', latency_ms: 5, error: null },
        redis: { status: 'up', latency_ms: 1, error: null },
        chroma: { status: 'down', latency_ms: null, error: '连接超时（mock 演示降级态）' },
      },
      embedding: { mode: 'cloud', model: 'qwen3.7-text-embedding-flash', dim: 1024, status: 'up' },
    }
    return data
  })
}

