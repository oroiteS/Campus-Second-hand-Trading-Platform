import { Pagination } from 'antd'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
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

/** 价格区间输入停顿多久后写入 URL 并取数（与列表页同口径，消除逐字符请求） */
const TEXT_DEBOUNCE_MS = 300

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

/**
 * 批量更新 URL query（空值删除；筛选变更时重置页码）。
 * replace：文本输入（价格区间）提交时为 true，避免逐字符压入历史记录；
 * 离散变更（下拉/翻页/搜索提交）保持 false，回退可还原上一筛选态。
 * 与当前 URL 等价时跳过，避免无谓导航。
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
  const query = next.toString()
  if (query === current.toString()) return
  navigate(`?${query}`, { replace: options?.replace === true })
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

  // 价格区间草稿：只承载「尚未提交的编辑」，与 typing 时的 URL 价格签名绑定；
  // 提交成功即清空草稿回落 URL 值 —— URL 始终是唯一真值
  // （q 由 SearchForm 的 key={q} 重挂载同步）。
  const priceTextKey = JSON.stringify([priceMin, priceMax])
  const [draftState, setDraftState] = useState<{
    key: string
    prices: { priceMin: string; priceMax: string }
  } | null>(null)

  // a 回退/前进断言：签名变化（回退/前进/直链/自身提交）即丢弃草稿，输入框立刻回落 URL 值
  // （渲染期修正 state，不在 effect 里 setState，也不给旧草稿「再前进时复活」的机会）
  if (draftState !== null && draftState.key !== priceTextKey) {
    setDraftState(null)
  }
  const priceDrafts =
    draftState !== null && draftState.key === priceTextKey
      ? draftState.prices
      : { priceMin, priceMax }
  const draftPriceMin = priceDrafts.priceMin
  const draftPriceMax = priceDrafts.priceMax

  /**
   * 提交一份价格草稿（防抖到期 / 失焦 / 回车 / 清空）：写 URL + 清草稿。
   * e 分页断言：页码归 1 只取决于「提交后的查询键是否变化」（next 与已提交值比较）。
   */
  const commitPrices = useCallback(
    (next: { priceMin: string; priceMax: string }, replace: boolean): void => {
      const changed = next.priceMin !== priceMin || next.priceMax !== priceMax
      setDraftState(null)
      applyParamPatch(
        navigate,
        searchParams,
        {
          price_min: next.priceMin.trim() || null,
          price_max: next.priceMax.trim() || null,
          ...(changed ? { page: null } : {}),
        },
        { replace },
      )
    },
    [navigate, searchParams, priceMin, priceMax],
  )

  // 草稿与已提交值不一致时才计时提交；b 卸载断言：cleanup 清定时器，卸载后不 navigate
  useEffect(() => {
    if (draftPriceMin === priceMin && draftPriceMax === priceMax) {
      return
    }
    const timer = window.setTimeout(
      () => commitPrices({ priceMin: draftPriceMin, priceMax: draftPriceMax }, true),
      TEXT_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(timer)
  }, [commitPrices, draftPriceMax, draftPriceMin, priceMax, priceMin])

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
  const { data, loading, fetching, error, retry } = useQueryList(fetchPage, enabled)

  /**
   * c 一致性断言：离散筛选（分类/成色）一次导航同时提交价格草稿并清空草稿，
   * 提交后框内显示即 URL 里的查询条件（不出现三方不一致）。
   */
  function handleFilterChange(patch: Partial<FilterValues>): void {
    const nextPrices = {
      priceMin: 'priceMin' in patch ? (patch.priceMin ?? '') : draftPriceMin,
      priceMax: 'priceMax' in patch ? (patch.priceMax ?? '') : draftPriceMax,
    }
    const textTouched = 'priceMin' in patch || 'priceMax' in patch
    const discreteTouched = 'categoryId' in patch || 'condition' in patch

    if (textTouched) {
      // 文本输入只落草稿，停顿 300ms（失焦/回车立即）后统一提交，避免逐字符一请求
      setDraftState({ key: priceTextKey, prices: nextPrices })
      // d 清空断言：删空立即清参（不等防抖），空值不写空串参数
      const cleared =
        (nextPrices.priceMin.trim() === '' && priceMin !== '') ||
        (nextPrices.priceMax.trim() === '' && priceMax !== '')
      if (cleared) commitPrices(nextPrices, true)
    }

    if (discreteTouched) {
      setDraftState(null)
      applyParamPatch(navigate, searchParams, {
        page: null,
        ...('categoryId' in patch
          ? { category: patch.categoryId != null ? String(patch.categoryId) : null }
          : {}),
        ...('condition' in patch ? { condition: patch.condition ?? null } : {}),
        price_min: nextPrices.priceMin.trim() || null,
        price_max: nextPrices.priceMax.trim() || null,
      })
    }
  }

  /** 翻页：作用于已提交查询键；有未提交草稿则随本次导航提交并归第 1 页 */
  function handlePageChange(next: number): void {
    const textChanged = draftPriceMin !== priceMin || draftPriceMax !== priceMax
    setDraftState(null)
    applyParamPatch(navigate, searchParams, {
      price_min: draftPriceMin.trim() || null,
      price_max: draftPriceMax.trim() || null,
      page: textChanged ? null : String(next),
    })
  }

  const filterValues: FilterValues = {
    categoryId,
    condition,
    priceMin: draftPriceMin,
    priceMax: draftPriceMax,
  }

  return (
    <div className="page-container">
      <PageHeader title="商品搜索" description="语义搜索：标题与描述相关的商品都能召回" />

      <SearchForm
        key={q}
        initialQ={q}
        onSearch={(nextQ) => {
          // 提交搜索词时一并提交价格草稿（与离散筛选同口径），页码归 1
          setDraftState(null)
          applyParamPatch(navigate, searchParams, {
            q: nextQ,
            page: null,
            price_min: draftPriceMin.trim() || null,
            price_max: draftPriceMax.trim() || null,
          })
        }}
      />

      <FilterBar
        idPrefix="product-search"
        values={filterValues}
        onChange={handleFilterChange}
        onCommitText={() => commitPrices({ priceMin: draftPriceMin, priceMax: draftPriceMax }, true)}
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
            empty={(data?.items.length ?? 0) === 0 && !fetching}
            emptyDescription="没有找到相关商品，换个关键词或放宽筛选试试"
          >
            {data && (
              <>
                <p className="product-list__meta" aria-live="polite">
                  「{q}」共 {data.total} 条结果
                  {data.degraded ? '（当前为标题匹配降级结果）' : '（按相关度排序）'}
                  {fetching ? ' · 更新中…' : ''}
                </p>
                <ul
                  className="product-grid"
                  aria-label="搜索结果列表"
                  aria-busy={fetching || undefined}
                >
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
