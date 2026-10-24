import { Pagination } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
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

/** 文本类筛选（关键词/价格）输入停顿多久后写入 URL 并取数（C-S-1：消除逐字符请求放大） */
const TEXT_DEBOUNCE_MS = 300

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

/** 文本类筛选的本地草稿（输入过程不写 URL，停顿/失焦/回车后才提交） */
interface TextDrafts {
  keyword: string
  priceMin: string
  priceMax: string
}

/** query 补丁：仅出现于补丁中的键会被更新，其余沿用当前 URL（null = 删除该参数） */
interface QueryPatch {
  categoryId?: number | null
  condition?: ProductCondition | null
  keyword?: string
  priceMin?: string
  priceMax?: string
  sort?: SortValue
  /** null = 重置页码（删除 page 参数） */
  page?: number | null
}

function setOrDelete(params: URLSearchParams, key: string, value: string | null): void {
  if (value == null || value === '') {
    params.delete(key)
  } else {
    params.set(key, value)
  }
}

/** 以当前 URL 为基底拼装下一份 query（保持未涉及参数与相对顺序不变） */
function buildQuery(base: URLSearchParams, patch: QueryPatch): string {
  const params = new URLSearchParams(base)
  if ('categoryId' in patch) {
    setOrDelete(params, 'category', patch.categoryId != null ? String(patch.categoryId) : null)
  }
  if ('condition' in patch) {
    setOrDelete(params, 'condition', patch.condition ?? null)
  }
  if ('keyword' in patch) {
    const keyword = patch.keyword ?? ''
    setOrDelete(params, 'keyword', keyword.trim() === '' ? null : keyword)
  }
  if ('priceMin' in patch) {
    const priceMin = patch.priceMin ?? ''
    setOrDelete(params, 'price_min', priceMin.trim() === '' ? null : priceMin.trim())
  }
  if ('priceMax' in patch) {
    const priceMax = patch.priceMax ?? ''
    setOrDelete(params, 'price_max', priceMax.trim() === '' ? null : priceMax.trim())
  }
  if ('sort' in patch) {
    setOrDelete(params, 'sort', patch.sort ?? null)
  }
  if ('page' in patch) {
    setOrDelete(params, 'page', patch.page != null ? String(patch.page) : null)
  }
  return params.toString()
}

/**
 * 商品列表页：FilterBar + 结果网格 + 分页。
 * - 筛选/排序/页码全部同步 URL query（可分享、刷新还原、回退不残留）；
 * - 关键词/价格输入先落本地草稿，停顿 300ms（失焦/回车立即）才写 URL 并取数，
 *   写 URL 一律 replace，避免逐字符请求与历史记录爆炸；回退/直链仍即时取数；
 * - URL 是唯一真值：urlTextKey（keyword/price_min/price_max 三元组）一变就用 URL 值
 *   覆盖草稿（回退/前进/直链/自身提交同一路径），草稿只承载「未提交的编辑」；
 *   清空输入立即提交（不等防抖）；离散筛选/排序/翻页一次导航带上当前草稿并归第 1 页；
 * - 价格区间预检（validators 同源）非法拦截不发请求，内联报错；
 * - 四态齐备：加载骨架 / 空（无在售商品）/ 错误可重试 / 正常；参数变化保留旧数据，
 *   由 meta 行的「更新中…」与 aria-busy 提供可感知的取数信号。
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

  return <ProductList searchParams={searchParams} navigate={navigate} />
}

interface ProductListProps {
  searchParams: URLSearchParams
  navigate: NavigateFunction
}

function ProductList({ searchParams, navigate }: ProductListProps) {
  const categoryId = parsePositiveInt(searchParams.get('category'))
  const condition = parseCondition(searchParams.get('condition'))
  const urlKeyword = searchParams.get('keyword') ?? ''
  const urlPriceMin = searchParams.get('price_min') ?? ''
  const urlPriceMax = searchParams.get('price_max') ?? ''
  const sort = parseSort(searchParams.get('sort'))
  const page = parsePositiveInt(searchParams.get('page')) ?? 1

  // 文本草稿：只承载「尚未提交的编辑」，且与 typing 发生时的 URL 文本签名绑定。
  // 提交成功即清空草稿（回落 URL 值），因此 URL 永远是唯一真值。
  const urlTextKey = JSON.stringify([urlKeyword, urlPriceMin, urlPriceMax])
  const [draftState, setDraftState] = useState<{ key: string; drafts: TextDrafts } | null>(null)

  // a 回退/前进断言：签名变化（回退/前进/直链/自身提交）即丢弃草稿，输入框立刻回落 URL 值。
  // 渲染期直接调整本组件状态（React 官方「渲染期间修正 state」用法），既不会在回退后
  // 残留旧草稿，也不会出现「回退丢弃、再前进又复活」的中间态，且避免 effect 级联渲染。
  if (draftState !== null && draftState.key !== urlTextKey) {
    setDraftState(null)
  }
  const drafts: TextDrafts =
    draftState !== null && draftState.key === urlTextKey
      ? draftState.drafts
      : { keyword: urlKeyword, priceMin: urlPriceMin, priceMax: urlPriceMax }
  const draftKeyword = drafts.keyword
  const draftPriceMin = drafts.priceMin
  const draftPriceMax = drafts.priceMax

  /** 以当前 URL 为基底应用补丁并导航；与当前 URL 一致时跳过（避免无谓导航） */
  const navigatePatch = useCallback(
    (base: URLSearchParams, patch: QueryPatch, replace: boolean): void => {
      const query = buildQuery(base, patch)
      if (query === base.toString()) return
      navigate(`?${query}`, { replace })
    },
    [navigate],
  )

  /**
   * 提交一份文本草稿（防抖到期 / 失焦 / 回车 / 清空）：写 URL + 清草稿。
   * e 分页断言：页码是否归 1，只取决于「提交后的查询键是否变化」
   * （next 与 URL 已提交值逐一比较），与草稿中间态无关，不会误重置或漏重置；
   * 空值由 buildQuery 删参，不写空字符串、不带空值发请求。
   */
  const commitText = useCallback(
    (next: TextDrafts, replace: boolean): void => {
      const textChanged =
        next.keyword !== urlKeyword ||
        next.priceMin !== urlPriceMin ||
        next.priceMax !== urlPriceMax
      setDraftState(null)
      navigatePatch(
        searchParams,
        {
          keyword: next.keyword,
          priceMin: next.priceMin,
          priceMax: next.priceMax,
          ...(textChanged ? { page: null } : {}),
        },
        replace,
      )
    },
    [navigatePatch, searchParams, urlKeyword, urlPriceMin, urlPriceMax],
  )

  // 草稿与已提交值不一致时才计时提交；replace 保留，不压历史（回退仍还原上一筛选态）。
  // b 卸载断言：cleanup 清定时器，因此离开页面绝不会在卸载后 navigate。
  useEffect(() => {
    if (
      draftKeyword === urlKeyword &&
      draftPriceMin === urlPriceMin &&
      draftPriceMax === urlPriceMax
    ) {
      return
    }
    const timer = window.setTimeout(
      () => commitText({ keyword: draftKeyword, priceMin: draftPriceMin, priceMax: draftPriceMax }, true),
      TEXT_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(timer)
  }, [
    commitText,
    draftKeyword,
    draftPriceMax,
    draftPriceMin,
    urlKeyword,
    urlPriceMax,
    urlPriceMin,
  ])

  // 价格区间预检（3.0 对照表同源）：非法输入拦截后不发请求
  const priceErrors = useMemo(
    () => ({
      min: validatePriceFilter(urlPriceMin, '价格下界') ?? undefined,
      max: validatePriceFilter(urlPriceMax, '价格上界') ?? undefined,
      range: validatePriceRange(urlPriceMin, urlPriceMax) ?? undefined,
    }),
    [urlPriceMin, urlPriceMax],
  )
  const priceInvalid = Boolean(priceErrors.min || priceErrors.max || priceErrors.range)

  // 关键词预检（契约 keyword ≤100 可空）：URL 直链超长同样拦截不发请求
  const keywordError = useMemo(
    () => validateKeywordOptional(urlKeyword) ?? undefined,
    [urlKeyword],
  )
  const blocked = priceInvalid || keywordError != null

  const fetchPage = useCallback((): Promise<Paginated<ProductSummary>> => {
    const min = urlPriceMin.trim() === '' ? undefined : Number(urlPriceMin)
    const max = urlPriceMax.trim() === '' ? undefined : Number(urlPriceMax)
    const kw = urlKeyword.trim()
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
  }, [categoryId, condition, urlPriceMin, urlPriceMax, urlKeyword, sort, page])

  const { data, loading, fetching, error, retry } = useQueryList(fetchPage, !blocked)

  const filterValues: FilterValues = {
    categoryId,
    condition,
    priceMin: drafts.priceMin,
    priceMax: drafts.priceMax,
    keyword: drafts.keyword,
  }

  /**
   * c 一致性断言：离散操作（分类/成色）一次导航同时提交当前草稿并清空草稿，
   * 因此 URL 里不会出现「框里 A、URL 里 B、结果按 B」的三方不一致——
   * 提交后草稿归零，框内显示即 URL 里的查询条件。
   */
  function handleFilterChange(patch: Partial<FilterValues>): void {
    const nextDrafts: TextDrafts = {
      keyword: 'keyword' in patch ? (patch.keyword ?? '') : drafts.keyword,
      priceMin: 'priceMin' in patch ? (patch.priceMin ?? '') : drafts.priceMin,
      priceMax: 'priceMax' in patch ? (patch.priceMax ?? '') : drafts.priceMax,
    }
    const textTouched = 'keyword' in patch || 'priceMin' in patch || 'priceMax' in patch
    const discreteTouched = 'categoryId' in patch || 'condition' in patch

    if (textTouched) {
      setDraftState({ key: urlTextKey, drafts: nextDrafts })
      // d 清空断言：删空输入立即提交（不等 300ms 防抖），空值由 buildQuery 删参，
      // 不写空串参数，也不会带空值发请求
      const cleared =
        (nextDrafts.keyword.trim() === '' && urlKeyword !== '') ||
        (nextDrafts.priceMin.trim() === '' && urlPriceMin !== '') ||
        (nextDrafts.priceMax.trim() === '' && urlPriceMax !== '')
      if (cleared) commitText(nextDrafts, true)
    }

    if (discreteTouched) {
      setDraftState(null)
      navigatePatch(
        searchParams,
        {
          categoryId: 'categoryId' in patch ? (patch.categoryId ?? null) : categoryId,
          condition: 'condition' in patch ? (patch.condition ?? null) : condition,
          keyword: nextDrafts.keyword,
          priceMin: nextDrafts.priceMin,
          priceMax: nextDrafts.priceMax,
          page: null,
        },
        false,
      )
    }
  }

  function handleSortChange(value: SortValue): void {
    setDraftState(null)
    navigatePatch(
      searchParams,
      {
        sort: value,
        keyword: drafts.keyword,
        priceMin: drafts.priceMin,
        priceMax: drafts.priceMax,
        page: null,
      },
      false,
    )
  }

  /**
   * 翻页：始终作用于「已提交查询键」。若存在未提交草稿，先随本次导航提交并按规则归第 1 页
   * （查询键变了就不能停在下一页，否则会出现空页/错页）。
   */
  function handlePageChange(next: number): void {
    const textChanged =
      drafts.keyword !== urlKeyword ||
      drafts.priceMin !== urlPriceMin ||
      drafts.priceMax !== urlPriceMax
    setDraftState(null)
    navigatePatch(
      searchParams,
      {
        keyword: drafts.keyword,
        priceMin: drafts.priceMin,
        priceMax: drafts.priceMax,
        page: textChanged ? null : next,
      },
      false,
    )
  }

  return (
    <div className="page-container">
      <PageHeader title="商品列表" description="本校在售商品，支持关键词 / 分类 / 成色 / 价格筛选" />

      <FilterBar
        idPrefix="product-list"
        values={filterValues}
        onChange={handleFilterChange}
        onCommitText={() => commitText(drafts, true)}
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
          empty={(data?.items.length ?? 0) === 0 && !fetching}
          emptyDescription="没有符合筛选条件的在售商品，换个条件试试"
        >
          {data && (
            <>
              <p className="product-list__meta" aria-live="polite">
                共 {data.total} 件商品
                {data.total > 0 ? ` · 第 ${data.page} / ${Math.max(data.pages, 1)} 页` : ''}
                {fetching ? ' · 更新中…' : ''}
              </p>
              <ul className="product-grid" aria-label="商品列表" aria-busy={fetching || undefined}>
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
