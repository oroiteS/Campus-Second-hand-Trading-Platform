// 业务类型入口：仅 re-export 契约生成类型（src/api/types.ts），禁止手写契约结构
import type { components, operations } from '../api/types'

export type { components, paths, operations } from '../api/types'

// ---- 系统（b0） ----
export type HealthData = components['schemas']['HealthData']
export type ServiceHealth = components['schemas']['ServiceHealth']
export type EmbeddingHealth = components['schemas']['EmbeddingHealth']

// ---- 用户域数据（b1 · 契约 0.2.0） ----
export type UserSummary = components['schemas']['UserSummary']
export type UserProfile = components['schemas']['UserProfile']
export type LoginData = components['schemas']['LoginData']
export type AuthApplication = components['schemas']['AuthApplication']
export type SchoolWithCampuses = components['schemas']['SchoolWithCampuses']
export type ImageRef = components['schemas']['ImageRef']
export type SchoolRef = components['schemas']['SchoolRef']
export type CampusRef = components['schemas']['CampusRef']

// ---- 用户域请求体（b1 · 契约 0.2.0） ----
export type RegisterInput = components['schemas']['RegisterInput']
export type LoginInput = components['schemas']['LoginInput']
export type PasswordResetInput = components['schemas']['PasswordResetInput']
export type ProfileUpdateInput = components['schemas']['ProfileUpdateInput']
export type PasswordChangeInput = components['schemas']['PasswordChangeInput']

// ---- 商品域数据（b2 · 契约 0.3.0） ----
export type ProductSummary = components['schemas']['ProductSummary']
export type ProductDetail = components['schemas']['ProductDetail']
export type ProductCondition = components['schemas']['ProductCondition']
export type ProductStatus = components['schemas']['ProductStatus']
export type CategoryRef = components['schemas']['CategoryRef']
export type FavoriteActionData = components['schemas']['FavoriteActionData']

// ---- 商品域请求体与查询参数（b2 · 契约 0.3.0，均取自生成物） ----
export type ProductCreateInput = components['schemas']['ProductCreateInput']
export type ProductStatusActionInput = components['schemas']['ProductStatusActionInput']
export type ProductListQuery = NonNullable<operations['listProducts']['parameters']['query']>
export type ProductSearchQuery = NonNullable<
  operations['searchProducts']['parameters']['query']
>
export type MyProductsQuery = NonNullable<
  operations['listMyProducts']['parameters']['query']
>

// ---- 分页 / 降级容器（由生成物组合，非手写契约结构） ----
/** 分页容器：契约 PaginatedData 的 items 元素类型由各列表接口具化 */
export type Paginated<T> = Omit<components['schemas']['PaginatedData'], 'items'> & {
  items: T[]
}
/** 契约降级可选字段：正常响应不带（false 语义），不得改写为必有 */
export type DegradedFields = { degraded?: boolean; degraded_reason?: string }
/** GET /recommendations/home 数据体 */
export type HomeFeedData = { items: ProductSummary[] } & DegradedFields
/** GET /products/search 数据体（PaginatedData 扩展可选降级字段） */
export type SearchResultData = Paginated<ProductSummary> & DegradedFields
/** GET /favorites/mine 条目：ProductSummary & { favorited_at } */
export type FavoriteItem = ProductSummary & { favorited_at: string }

/**
 * POST /auth/logout 数据体：正常为空对象；Redis 故障降级时附
 * degraded: true 与 degraded_reason（黑名单未落，令牌有效至自然过期）。
 */
export type LogoutData = DegradedFields

// ---- 业务枚举 ----
export type Role = components['schemas']['Role']
export type AuthStatus = components['schemas']['AuthStatus']
export type UserAccountStatus = components['schemas']['UserAccountStatus']
