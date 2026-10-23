import type {
  MyProductsQuery,
  Paginated,
  ProductCreateInput,
  ProductDetail,
  ProductListQuery,
  ProductSearchQuery,
  ProductStatusActionInput,
  ProductSummary,
  SearchResultData,
} from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import {
  mockChangeProductStatus,
  mockCreateProduct,
  mockDeleteProduct,
  mockGetProduct,
  mockListMyProducts,
  mockListProducts,
  mockSearchProducts,
  mockUpdateProduct,
} from './mock/products'

/** GET /api/products：本校在售商品分页列表（分类/成色/价格区间/校区/关键词/排序筛选） */
export function listProducts(query: ProductListQuery): Promise<Paginated<ProductSummary>> {
  if (USE_MOCK) {
    return mockListProducts(query)
  }
  return http
    .get<Paginated<ProductSummary>>('/products', { params: query })
    .then((res) => res.data)
}

/** GET /api/products/{id}：商品详情（含 is_favorited / view_count / 图集） */
export function getProduct(id: number): Promise<ProductDetail> {
  if (USE_MOCK) {
    return mockGetProduct(id)
  }
  return http.get<ProductDetail>(`/products/${id}`).then((res) => res.data)
}

/** POST /api/products：发布商品（发布即上架；9001 字段级错误含 image_ids 归属/数量） */
export function createProduct(body: ProductCreateInput): Promise<ProductDetail> {
  if (USE_MOCK) {
    return mockCreateProduct(body)
  }
  return http.post<ProductDetail>('/products', body).then((res) => res.data)
}

/** PUT /api/products/{id}：编辑商品（仅发布者；image_ids 全量替换，数组序 = 排序） */
export function updateProduct(
  id: number,
  body: ProductCreateInput,
): Promise<ProductDetail> {
  if (USE_MOCK) {
    return mockUpdateProduct(id, body)
  }
  return http.put<ProductDetail>(`/products/${id}`, body).then((res) => res.data)
}

/** PATCH /api/products/{id}/status：上架 / 下架（目标状态仅二值） */
export function changeProductStatus(
  id: number,
  status: ProductStatusActionInput['status'],
): Promise<ProductSummary> {
  if (USE_MOCK) {
    return mockChangeProductStatus(id, status)
  }
  return http
    .patch<ProductSummary>(`/products/${id}/status`, { status })
    .then((res) => res.data)
}

/** DELETE /api/products/{id}：删除商品（软删；trading/sold → 3001） */
export function deleteProduct(id: number): Promise<void> {
  if (USE_MOCK) {
    return mockDeleteProduct(id)
  }
  return http.delete<void>(`/products/${id}`).then(() => undefined)
}

/** GET /api/products/mine：我的商品（按状态筛选，created_at 倒序） */
export function listMyProducts(query: MyProductsQuery): Promise<Paginated<ProductSummary>> {
  if (USE_MOCK) {
    return mockListMyProducts(query)
  }
  return http
    .get<Paginated<ProductSummary>>('/products/mine', { params: query })
    .then((res) => res.data)
}

/** GET /api/products/search：向量搜索（q 必填 1–100，由调用方预检拦截空值不发请求） */
export function searchProducts(
  q: string,
  filters: Omit<ProductSearchQuery, 'q'>,
): Promise<SearchResultData> {
  if (USE_MOCK) {
    return mockSearchProducts(q, filters)
  }
  return http
    .get<SearchResultData>('/products/search', { params: { q, ...filters } })
    .then((res) => res.data)
}
