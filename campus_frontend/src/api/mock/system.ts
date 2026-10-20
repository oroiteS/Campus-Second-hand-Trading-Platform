import dayjs from 'dayjs'
import type { UserSummary } from '../../types'
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

/** 演示用用户概要（批次 0 无登录接口，结构与 UserSummary 同构） */
export const DEMO_USERS: Record<'unverified' | 'student' | 'admin', UserSummary> = {
  unverified: {
    id: 1001,
    display_name: '小明',
    nickname: '小明',
    auth_status: 'unverified',
    role: 'student',
  },
  student: {
    id: 1002,
    display_name: '小明-示例大学(东校区)',
    nickname: '小明',
    auth_status: 'approved',
    role: 'student',
  },
  admin: {
    id: 9001,
    display_name: '管理员',
    nickname: '管理员',
    auth_status: 'approved',
    role: 'admin',
  },
}
