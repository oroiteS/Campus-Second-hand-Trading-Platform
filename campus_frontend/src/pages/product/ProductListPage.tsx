import { Pagination } from 'antd'
import { useCallback, useMemo } from 'react'
import {
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
  type NavigateFunction,
} from 'react-router-dom'
import { listProducts } from '../../api/products'
import { FilterBar, type FilterValues, type SortValue } from '../../components/FilterBar'
import { PageHeader } from '../../components/PageHeader'
import { ProductCard } from '../../components/ProductCard'
import { StateView } from '../../components/StateView'
import { useQueryList } from '../../hooks/useQueryList'
import { useAuthPhase } from '../../stores/authStore'
import type { Paginated, ProductCondition, ProductSummary } from '../../types'
import {
  validateKeywordOptional,
  validatePriceFilter,
  validatePriceRange,
} from '../../utils/validators'
import './product.css'

const PAGE_SIZE = 20

const CONDITIONS: readonly ProductCondition[] = [
  'brand_new',
  'as_new',
  'excellent',
  'good',
  'fair',
]

const SORTS: readonly SortValue[] = ['newest', 'price_asc', 'price_desc']

/** URL query 参数解析（容错：非法值回落缺省，保证可分享链接不崩） */
function parsePositiveInt(value: string | null): number | null {
  if (value == null || value === '') return null
  const num = Number(value)
  return Number.isInteger(num) && num > 0 ? num : null
}

function parseCondition(value: string | null): ProductCondition | null {
  return CONDITIONS.find((item) => item === value) ?? null
}

function parseSort(value: string | null): SortValue {
  return SORTS.find((item) => item === value) ?? 'newest'
}

/**
 * 批量更新 URL query（空值删除；筛选/排序变更时重置页码）。
 * replace：逐字符输入（价格/关键词）过程中为 true，避免每个字符压入一条历史记录；
 * 离散变更（下拉/排序/翻页/提交语义）保持 false，回退可还原上一筛选态。
 */
function applyParamPatch(
  navigate: NavigateFunction,
  current: URLSearchParams,
  patch: Record<string, string | null>,
  options?: { replace?: boolean },
): void {
  const next = new URLSearchParams(current)
  for (const [key, value] of Object.entries(patch)) {
    if (value == null || value === '') {
      next.delete(key)
    } else {
      next.set(key, value)
    }
  }
  navigate(`?${next.toString()}`, { replace: options?.replace === true })
}

/**
 * 商品列表页：FilterBar + 结果网格 + 分页。
 * - 筛选/排序/页码全部同步 URL query（可分享、刷新还原、回退不残留）；
 * - 价格区间预检（validators 同源）非法拦截不发请求，内联报错；
 * - 四态齐备：加载骨架 / 空（无在售商品）/ 错误可重试 / 正常。
 */
export function ProductListPage() {
  const phase = useAuthPhase()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 页面入口守卫（与路由层 RequireVerified 双层拦截）
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }

  return (
    <ProductList
      searchParams={searchParams}
      navigate={navigate}
    />
  )
}

interface ProductListProps {
  searchParams: URLSearchParams
  navigate: NavigateFunction
}

function ProductList({ searchParams, navigate }: ProductListProps) {
  const categoryId = parsePositiveInt(searchParams.get('category'))
  const condition = parseCondition(searchParams.get('condition'))
  const priceMin = searchParams.get('price_min') ?? ''
  const priceMax = searchParams.get('price_max') ?? ''
  const sort = parseSort(searchParams.get('sort'))
  const keyword = searchParams.get('keyword') ?? ''
  const page = parsePositiveInt(searchParams.get('page')) ?? 1

  // 价格区间预检（3.0 对照表同源）：非法输入拦截后不发请求
  const priceErrors = useMemo(
    () => ({
      min: validatePriceFilter(priceMin, '价格下界') ?? undefined,
      max: validatePriceFilter(priceMax, '价格上界') ?? undefined,
      range: validatePriceRange(priceMin, priceMax) ?? undefined,
    }),
    [priceMin, priceMax],
  )
  const priceInvalid = Boolean(priceErrors.min || priceErrors.max || priceErrors.range)

  // 关键词预检（契约 keyword ≤100 可空）：URL 直链超长同样拦截不发请求
  const keywordError = useMemo(
    () => validateKeywordOptional(keyword) ?? undefined,
    [keyword],
  )
  const blocked = priceInvalid || keywordError != null

  const fetchPage = useCallback((): Promise<Paginated<ProductSummary>> => {
    const min = priceMin.trim() === '' ? undefined : Number(priceMin)
    const max = priceMax.trim() === '' ? undefined : Number(priceMax)
    const kw = keyword.trim()
    return listProducts({
      ...(categoryId != null ? { category_id: categoryId } : {}),
      ...(condition != null ? { condition } : {}),
      ...(min != null ? { price_min: min } : {}),
      ...(max != null ? { price_max: max } : {}),
      ...(kw !== '' ? { keyword: kw } : {}),
      sort,
      page,
      page_size: PAGE_SIZE,
    })
  }, [categoryId, condition, priceMin, priceMax, keyword, sort, page])

  const { data, loading, error, retry } = useQueryList(fetchPage, !blocked)

  const filterValues: FilterValues = { categoryId, condition, priceMin, priceMax, keyword }

  function handleFilterChange(patch: Partial<FilterValues>): void {
    const next: Record<string, string | null> = { page: null }
    if ('categoryId' in patch) {
      next.category = patch.categoryId != null ? String(patch.categoryId) : null
    }
    if ('condition' in patch) {
      next.condition = patch.condition ?? null
    }
    if ('priceMin' in patch) {
      next.price_min = patch.priceMin?.trim() || null
    }
    if ('priceMax' in patch) {
      next.price_max = patch.priceMax?.trim() || null
    }
    if ('keyword' in patch) {
      next.keyword = patch.keyword?.trim() || null
    }
    // 逐字符输入（价格/关键词）过程 replace:true 防历史记录爆炸；离散变更保留回退语义
    const typing =
      'priceMin' in patch || 'priceMax' in patch || 'keyword' in patch
    applyParamPatch(navigate, searchParams, next, { replace: typing })
  }

  function handleSortChange(value: SortValue): void {
    applyParamPatch(navigate, searchParams, { sort: value, page: null })
  }

  function handlePageChange(next: number): void {
    applyParamPatch(navigate, searchParams, { page: String(next) })
  }

  return (
    <div className="page-container">
      <PageHeader title="商品列表" description="本校在售商品，支持关键词 / 分类 / 成色 / 价格筛选" />

      <FilterBar
        idPrefix="product-list"
        values={filterValues}
        onChange={handleFilterChange}
        sort={sort}
        onSortChange={handleSortChange}
        priceErrors={priceErrors}
        keywordError={keywordError}
        showKeyword
      />

      {blocked ? (
        <p className="form-field__error product-list__blocked" role="alert">
          {keywordError ?? '请先修正价格区间的错误后再查询'}
        </p>
      ) : (
        <StateView
          loading={loading}
          error={error}
          onRetry={retry}
          empty={(data?.items.length ?? 0) === 0}
          emptyDescription="没有符合筛选条件的在售商品，换个条件试试"
        >
          {data && (
            <>
              <p className="product-list__meta" aria-live="polite">
                共 {data.total} 件商品
                {data.total > 0 ? ` · 第 ${data.page} / ${Math.max(data.pages, 1)} 页` : ''}
              </p>
              <ul className="product-grid" aria-label="商品列表">
                {data.items.map((product) => (
                  <li key={product.id}>
                    <ProductCard product={product} />
                  </li>
                ))}
              </ul>
              <Pagination
                className="product-list__pagination"
                current={data.page}
                total={data.total}
                pageSize={data.page_size}
                showSizeChanger={false}
                hideOnSinglePage
                onChange={handlePageChange}
              />
            </>
          )}
        </StateView>
      )}
    </div>
  )
}
