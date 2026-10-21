import type { SchoolWithCampuses } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockListSchools } from './mock/schools'

/** GET /api/schools：学校与校区公开列表（游客可查；仅启用，按名称排序，不分页） */
export function listSchools(): Promise<SchoolWithCampuses[]> {
  if (USE_MOCK) {
    return mockListSchools()
  }
  return http.get<SchoolWithCampuses[]>('/schools').then((res) => res.data)
}
