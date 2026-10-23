import type { CategoryRef } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockListCategories } from './mock/categories'

/** GET /api/categories：启用分类列表（sort_order 升序，不分页；发布/筛选共用） */
export function listCategories(): Promise<CategoryRef[]> {
  if (USE_MOCK) {
    return mockListCategories()
  }
  return http.get<CategoryRef[]>('/categories').then((res) => res.data)
}
