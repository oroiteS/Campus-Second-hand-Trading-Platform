import type { HomeFeedData } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockGetHomeFeed } from './mock/recommendations'

/**
 * GET /api/recommendations/home：首页推荐（≤ 40 个本校在售，排除自己发布）。
 * `refresh = true` 绕过缓存强制重算（「换一批」）；降级时 data 附 degraded 字段。
 */
export function getHomeFeed(refresh?: boolean): Promise<HomeFeedData> {
  if (USE_MOCK) {
    return mockGetHomeFeed(refresh)
  }
  return http
    .get<HomeFeedData>('/recommendations/home', {
      params: refresh ? { refresh: 'true' } : undefined,
    })
    .then((res) => res.data)
}
