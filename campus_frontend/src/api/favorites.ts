import type { FavoriteActionData, FavoriteItem, Paginated } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import {
  mockFavoriteProduct,
  mockListMyFavorites,
  mockUnfavoriteProduct,
} from './mock/favorites'

/** POST /api/products/{id}/favorite：收藏商品（重复收藏 → 9003；非在售 → 3001） */
export function favoriteProduct(id: number): Promise<FavoriteActionData> {
  if (USE_MOCK) {
    return mockFavoriteProduct(id)
  }
  return http.post<FavoriteActionData>(`/products/${id}/favorite`).then((res) => res.data)
}

/** DELETE /api/products/{id}/favorite：取消收藏（幂等，未收藏同样 200） */
export function unfavoriteProduct(id: number): Promise<FavoriteActionData> {
  if (USE_MOCK) {
    return mockUnfavoriteProduct(id)
  }
  return http
    .delete<FavoriteActionData>(`/products/${id}/favorite`)
    .then((res) => res.data)
}

/** GET /api/favorites/mine：我的收藏列表（favorited_at 倒序；含非在售置灰条目） */
export function listMyFavorites(
  page = 1,
  pageSize = 20,
): Promise<Paginated<FavoriteItem>> {
  if (USE_MOCK) {
    return mockListMyFavorites(page, pageSize)
  }
  return http
    .get<Paginated<FavoriteItem>>('/favorites/mine', {
      params: { page, page_size: pageSize },
    })
    .then((res) => res.data)
}
