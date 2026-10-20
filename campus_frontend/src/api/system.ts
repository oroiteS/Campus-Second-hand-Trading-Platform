import { http } from './http'
import { USE_MOCK } from './config'
import { mockGetHealth } from './mock/system'
import type { components } from './types'

type HealthData = components['schemas']['HealthData']

export type { HealthData }

/** GET /api/health：健康检查（公开）。VITE_USE_MOCK=true 时走契约同构 mock */
export function getHealth(): Promise<HealthData> {
  if (USE_MOCK) {
    return mockGetHealth()
  }
  return http.get<HealthData>('/health').then((res) => res.data)
}
