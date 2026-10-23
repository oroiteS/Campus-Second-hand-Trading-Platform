import dayjs from 'dayjs'
import type { FavoriteActionData, FavoriteItem, Paginated } from '../../types'
import { delay } from '../../utils/delay'
import { PRODUCT_STATUS_TEXT } from '../../utils/statusText'
import { ApiError } from '../http'
import {
  addFavoriteRecord,
  favoritesOfUser,
  findProduct,
  removeFavoriteRecord,
  requireVerifiedStudentFor,
  toProductSummary,
  visibleProductForFavorite,
} from './products'
import { requireVerifiedSession } from './users'

/** 分页切片（与 products mock 同口径：page ≥ 1；空表 pages = 0） */
function paginate<T>(items: T[], page: number, pageSize: number): Paginated<T> {
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

/**
 * POST /api/products/{id}/favorite：收藏（仅本校 on_sale；重复 → 9003；
 * 非 on_sale → 3001；不可见/不存在 → 404/9002 防探测；管理员 → 9003）。
 */
export function mockFavoriteProduct(id: number): Promise<FavoriteActionData> {
  return delay(300).then(() => {
    const user = requireVerifiedStudentFor('收藏商品')
    const product = visibleProductForFavorite(id, user)
    if (!product) {
      throw new ApiError(9002, '商品不存在', null)
    }
    if (product.status !== 'on_sale') {
      throw new ApiError(
        3001,
        `商品当前状态为${PRODUCT_STATUS_TEXT[product.status]}，仅上架商品可收藏`,
        null,
      )
    }
    if (favoritesOfUser(user.id).has(id)) {
      throw new ApiError(9003, '已收藏该商品', null)
    }
    addFavoriteRecord(user.id, id, dayjs().format('YYYY-MM-DDTHH:mm:ssZ'))
    product.favoriteCount += 1
    return { favorited: true, favorite_count: product.favoriteCount }
  })
}

/**
 * DELETE /api/products/{id}/favorite：取消收藏（幂等，未收藏同样 200；
 * 商品非本校/不存在仍 404/9002；管理员 → 9003，与收藏同口径）。
 * 已下架/已售条目仍可取消（收藏列表置灰条目出口）。
 */
export function mockUnfavoriteProduct(id: number): Promise<FavoriteActionData> {
  return delay(300).then(() => {
    // 取消收藏与收藏同口径：仅学生可操作（管理员 → 9003）
    const user = requireVerifiedStudentFor('取消收藏')
    const product = visibleProductForFavorite(id, user)
    if (!product) {
      throw new ApiError(9002, '商品不存在', null)
    }
    const had = removeFavoriteRecord(user.id, id)
    if (had) {
      product.favoriteCount = Math.max(0, product.favoriteCount - 1)
    }
    return { favorited: false, favorite_count: product.favoriteCount }
  })
}

/**
 * GET /api/favorites/mine：收藏列表（favorited_at 倒序；含 off_sale/sold/trading
 * 条目供前端置灰与取消；deleted 恒不返回）。
 */
export function mockListMyFavorites(
  page = 1,
  pageSize = 20,
): Promise<Paginated<FavoriteItem>> {
  return delay(350).then(() => {
    const user = requireVerifiedSession()
    const items: FavoriteItem[] = []
    favoritesOfUser(user.id).forEach((favoritedAt, productId) => {
      const product = findProduct(productId)
      // deleted 商品条目不返回（收藏记录保留但不可见，契约语义）
      if (product && product.status !== 'deleted') {
        items.push({ ...toProductSummary(product), favorited_at: favoritedAt })
      }
    })
    items.sort((a, b) => b.favorited_at.localeCompare(a.favorited_at))
    return paginate(items, page, pageSize)
  })
}
