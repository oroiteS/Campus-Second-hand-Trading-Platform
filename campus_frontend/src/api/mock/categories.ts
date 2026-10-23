import type { CategoryRef } from '../../types'
import { delay } from '../../utils/delay'

/**
 * GET /api/categories 契约同构 mock：全部启用分类，
 * 按 sort_order 升序、id 升序；不分页（全局分类量小）。
 * 本文件是分类数据的唯一持有处，products mock 引用同一常量做 9001 复验，
 * 避免两处漂移。
 */
export const MOCK_CATEGORIES: CategoryRef[] = [
  { id: 1, name: '数码电子' },
  { id: 2, name: '图书教材' },
  { id: 3, name: '生活用品' },
  { id: 4, name: '运动户外' },
  { id: 5, name: '服饰鞋包' },
  { id: 6, name: '其他' },
]

export function mockListCategories(): Promise<CategoryRef[]> {
  return delay(250).then(() => MOCK_CATEGORIES.map((category) => ({ ...category })))
}
