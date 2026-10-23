import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getHomeFeed } from '../../api/recommendations'
import { DegradedBanner } from '../../components/DegradedBanner'
import { PageHeader } from '../../components/PageHeader'
import { ProductCard } from '../../components/ProductCard'
import { StateView } from '../../components/StateView'
import { useAuthPhase } from '../../stores/authStore'
import type { HomeFeedData } from '../../types'
import { errorMessage, isTokenInvalidError } from '../../utils/apiError'
import { validateSearchQ } from '../../utils/validators'
import './HomePage.css'

/**
 * 首页（b2 原地改造）：个性化推荐宫格（≤40 个，移动 2 列 / ≥1024px 5 列）。
 * - 「换一批」refresh=true 绕过缓存重算；加载骨架 aria-busy；空态区分管理员；
 * - degraded 提示条（DegradedBanner）；搜索框与列表页入口导航；
 * - 冷启动与画像态对前端无感知（mock 与真实接口同构）。
 */
export function HomePage() {
  const phase = useAuthPhase()
  const navigate = useNavigate()

  const [feed, setFeed] = useState<HomeFeedData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [searchDraft, setSearchDraft] = useState('')
  const [searchError, setSearchError] = useState<string | null>(null)

  // 首次加载：初始 loading 已为 true，effect 内仅异步落盘（不同步 setState）
  useEffect(() => {
    let cancelled = false
    getHomeFeed(false)
      .then((data) => {
        if (cancelled) return
        setFeed(data)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (!isTokenInvalidError(err)) {
          setError(errorMessage(err, '推荐加载失败，请稍后重试'))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  /** 事件侧重载（重试 / 换一批）：可同步置位加载态 */
  const reload = useCallback((refresh = false) => {
    if (refresh) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)
    getHomeFeed(refresh)
      .then((data) => {
        setFeed(data)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!isTokenInvalidError(err)) {
          setError(errorMessage(err, '推荐加载失败，请稍后重试'))
        }
      })
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }, [])

  function handleSearch(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    const q = searchDraft.trim()
    if (q === '') {
      setSearchError('请输入搜索词')
      return
    }
    const invalid = validateSearchQ(q)
    if (invalid) {
      setSearchError(invalid)
      return
    }
    setSearchError(null)
    navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  const isEmpty = (feed?.items.length ?? 0) === 0

  return (
    <div className="page-container">
      <PageHeader title="校园二手交易平台" description="本校学生自发的二手好物集市" />

      <div className="home-entry">
        <form className="home-entry__search" role="search" onSubmit={handleSearch} noValidate>
          <label htmlFor="home-search-input" className="visually-hidden">
            搜索商品
          </label>
          <input
            id="home-search-input"
            type="search"
            value={searchDraft}
            onChange={(e) => {
              setSearchDraft(e.target.value)
              setSearchError(null)
            }}
            placeholder="搜索想要的宝贝，如：机械键盘"
            aria-invalid={searchError ? true : undefined}
            aria-describedby={searchError ? 'home-search-error' : undefined}
          />
          <button type="submit" disabled={loading}>
            搜索
          </button>
          {searchError && (
            <p id="home-search-error" className="form-field__error" role="alert">
              {searchError}
            </p>
          )}
        </form>
        <div className="home-entry__links">
          <Link to="/products">全部商品</Link>
          {phase === 'student' && (
            <Link to="/publish" className="home-entry__publish">
              发布商品
            </Link>
          )}
        </div>
      </div>

      <section aria-labelledby="home-feed-heading">
        <div className="home-feed-head">
          <h2 id="home-feed-heading">为你推荐</h2>
          {phase !== 'admin' && feed != null && feed.items.length > 0 && (
            <button
              type="button"
              className="home-feed-head__refresh"
              onClick={() => reload(true)}
              disabled={loading || refreshing}
              aria-label="换一批推荐商品"
            >
              {refreshing ? '更换中…' : '换一批'}
            </button>
          )}
        </div>

        {feed?.degraded && <DegradedBanner reason={feed.degraded_reason} />}

        <StateView
          loading={loading}
          error={error}
          onRetry={() => reload()}
          empty={isEmpty}
          emptyDescription={
            phase === 'admin'
              ? '管理员账号无个性化推荐'
              : '本校暂无在售商品，等你发布第一件'
          }
        >
          {feed && (
            <ul
              className="product-grid home-feed-grid"
              aria-busy={refreshing || undefined}
              aria-label="推荐商品列表"
            >
              {feed.items.map((product) => (
                <li key={product.id}>
                  <ProductCard product={product} />
                </li>
              ))}
            </ul>
          )}
        </StateView>
      </section>
    </div>
  )
}
