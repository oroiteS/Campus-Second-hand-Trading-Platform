import type { Paginated } from '../../types'

/**
 * 分页切片（契约 PaginatedData 唯一实现，products / favorites mock 共用）：
 * - page ≥ 1，越界自动收敛到 [1, pages]（空表收敛为 1）；
 * - page_size 收敛到 [1, 100]；
 * - pages = ceil(total / page_size)，空表为 0。
 */
export function paginate<T>(items: T[], page: number, pageSize: number): Paginated<T> {
  const total = items.length
  const pages = Math.ceil(total / pageSize)
  const safePageSize = Math.min(Math.max(1, pageSize), 100)
  const safePage = Math.min(Math.max(1, page), Math.max(pages, 1))
  const start = (safePage - 1) * safePageSize
  return {
    items: items.slice(start, start + safePageSize),
    page: safePage,
    page_size: safePageSize,
    total,
    pages,
  }
}
