import { Pagination } from 'antd'
import { useCallback, useMemo, useState, type FormEvent } from 'react'
import {
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
  type NavigateFunction,
} from 'react-router-dom'
import { searchProducts } from '../../api/products'
import { DegradedBanner } from '../../components/DegradedBanner'
import { FilterBar, type FilterValues } from '../../components/FilterBar'
import { PageHeader } from '../../components/PageHeader'
import { ProductCard } from '../../components/ProductCard'
import { StateView } from '../../components/StateView'
import { useQueryList } from '../../hooks/useQueryList'
import { useAuthPhase } from '../../stores/authStore'
import type { ProductCondition, ProductSummary, SearchResultData } from '../../types'
import { validatePriceFilter, validatePriceRange, validateSearchQ } from '../../utils/validators'
import './product.css'

const PAGE_SIZE = 20

const CONDITIONS: readonly ProductCondition[] = [
  'brand_new',
  'as_new',
  'excellent',
  'good',
  'fair',
]

function parsePositiveInt(value: string | null): number | null {
  if (value == null || value === '') return null
  const num = Number(value)
  return Number.isInteger(num) && num > 0 ? num : null
}

function parseCondition(value: string | null): ProductCondition | null {
  return CONDITIONS.find((item) => item === value) ?? null
}

function applyParamPatch(
  navigate: NavigateFunction,
  current: URLSearchParams,
  patch: Record<string, string | null>,
): void {
  const next = new URLSearchParams(current)
  for (const [key, value] of Object.entries(patch)) {
    if (value == null || value === '') {
      next.delete(key)
    } else {
      next.set(key, value)
    }
  }
  navigate(`?${next.toString()}`, { replace: false })
}

/**
 * 搜索页：q 必填预检（空值/超长不发请求）→ 相似度序结果（无排序控件）+
 * FilterBar（无排序子项）+ 分页；DegradedBanner 降级提示；
 * q 与筛选全部同步 URL query（可分享、刷新还原）。
 */
export function SearchPage() {
  const phase = useAuthPhase()
  const location = useLocation()

  // 页面入口守卫（与路由层 RequireVerified 双层拦截）
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }

  return <SearchViewInner />
}

function SearchViewInner() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const q = searchParams.get('q')?.trim() ?? ''
  const categoryId = parsePositiveInt(searchParams.get('category'))
  const condition = parseCondition(searchParams.get('condition'))
  const priceMin = searchParams.get('price_min') ?? ''
  const priceMax = searchParams.get('price_max') ?? ''
  const page = parsePositiveInt(searchParams.get('page')) ?? 1

  // URL 级 q 合法性（直接粘贴超长 q 的链接也拦截，不发请求）
  const urlQError = q === '' ? null : validateSearchQ(q)

  // 价格区间预检：非法拦截后不发请求
  const priceErrors = useMemo(
    () => ({
      min: validatePriceFilter(priceMin, '价格下界') ?? undefined,
      max: validatePriceFilter(priceMax, '价格上界') ?? undefined,
      range: validatePriceRange(priceMin, priceMax) ?? undefined,
    }),
    [priceMin, priceMax],
  )
  const priceInvalid = Boolean(priceErrors.min || priceErrors.max || priceErrors.range)

  const fetchPage = useCallback((): Promise<SearchResultData> => {
    const min = priceMin.trim() === '' ? undefined : Number(priceMin)
    const max = priceMax.trim() === '' ? undefined : Number(priceMax)
    return searchProducts(q, {
      ...(categoryId != null ? { category_id: categoryId } : {}),
      ...(condition != null ? { condition } : {}),
      ...(min != null ? { price_min: min } : {}),
      ...(max != null ? { price_max: max } : {}),
      page,
      page_size: PAGE_SIZE,
    })
  }, [q, categoryId, condition, priceMin, priceMax, page])

  const enabled = q !== '' && urlQError == null && !priceInvalid
  const { data, loading, error, retry } = useQueryList(fetchPage, enabled)

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
    applyParamPatch(navigate, searchParams, next)
  }

  function handlePageChange(next: number): void {
    applyParamPatch(navigate, searchParams, { page: String(next) })
  }

  const filterValues: FilterValues = { categoryId, condition, priceMin, priceMax }

  return (
    <div className="page-container">
      <PageHeader title="商品搜索" description="语义搜索：标题与描述相关的商品都能召回" />

      <SearchForm
        key={q}
        initialQ={q}
        onSearch={(nextQ) => applyParamPatch(navigate, searchParams, { q: nextQ, page: null })}
      />

      <FilterBar
        idPrefix="product-search"
        values={filterValues}
        onChange={handleFilterChange}
        priceErrors={priceErrors}
      />

      {urlQError ? (
        <p className="form-field__error product-list__blocked" role="alert">
          {urlQError}
        </p>
      ) : q === '' ? (
        <p className="product-list__meta">输入关键词开始搜索，例如「机械键盘」。</p>
      ) : priceInvalid ? (
        <p className="form-field__error product-list__blocked" role="alert">
          请先修正价格区间的错误后再查询
        </p>
      ) : (
        <>
          {data?.degraded && <DegradedBanner reason={data.degraded_reason} />}
          <StateView
            loading={loading}
            error={error}
            onRetry={retry}
            empty={(data?.items.length ?? 0) === 0}
            emptyDescription="没有找到相关商品，换个关键词或放宽筛选试试"
          >
            {data && (
              <>
                <p className="product-list__meta" aria-live="polite">
                  「{q}」共 {data.total} 条结果
                  {data.degraded ? '（当前为标题匹配降级结果）' : '（按相关度排序）'}
                </p>
                <ul className="product-grid" aria-label="搜索结果列表">
                  {data.items.map((product: ProductSummary) => (
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
        </>
      )}
    </div>
  )
}

interface SearchFormProps {
  initialQ: string
  onSearch: (q: string) => void
}

/** 搜索表单（key 随 URL q 重挂载，草稿与 URL 初值同步） */
function SearchForm({ initialQ, onSearch }: SearchFormProps) {
  const [draft, setDraft] = useState(initialQ)
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    const q = draft.trim()
    // q 必填预检：空值/超长不发请求（不导航）
    const invalid = q === '' ? '请输入搜索词' : validateSearchQ(q)
    if (invalid) {
      setError(invalid)
      return
    }
    setError(null)
    onSearch(q)
  }

  return (
    <form className="search-page__form" role="search" onSubmit={handleSubmit} noValidate>
      <label htmlFor="search-page-input" className="visually-hidden">
        搜索商品
      </label>
      <input
        id="search-page-input"
        type="search"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setError(null)
        }}
        placeholder="搜索想要的宝贝，如：机械键盘"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? 'search-page-error' : 'search-page-hint'}
      />
      <button type="submit" aria-describedby={error ? 'search-page-error' : undefined}>
        搜索
      </button>
      <p id="search-page-hint" className="form-field__hint">
        1–100 个字符；支持语义匹配，描述相关也能召回。
      </p>
      {error && (
        <p id="search-page-error" className="form-field__error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
