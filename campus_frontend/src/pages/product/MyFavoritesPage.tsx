import { Button, Pagination } from 'antd'
import { useCallback, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { listMyFavorites, unfavoriteProduct } from '../../api/favorites'
import { PageHeader } from '../../components/PageHeader'
import { ProductCard } from '../../components/ProductCard'
import { StateView } from '../../components/StateView'
import { useQueryList } from '../../hooks/useQueryList'
import { useAuthPhase } from '../../stores/authStore'
import type { FavoriteItem, Paginated } from '../../types'
import { errorMessage, isTokenInvalidError } from '../../utils/apiError'
import { formatDateTime } from '../../utils/format'
import './product.css'

const PAGE_SIZE = 20

/**
 * 我的收藏：收藏时间倒序列表（含 off_sale/sold/trading 条目——置灰 + 状态徽章，
 * 仍可取消收藏）；deleted 条目后端不返回。空态引导去逛逛。
 */
export function MyFavoritesPage() {
  const phase = useAuthPhase()
  const location = useLocation()

  // 页面入口守卫（与路由层 RequireStudent 双层拦截）
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }
  if (phase === 'admin') {
    return <Navigate to="/" replace />
  }

  return <MyFavorites />
}

function MyFavorites() {
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  /** 已取消的条目（就地移除，等待下次取数自然对齐） */
  const [removedIds, setRemovedIds] = useState<ReadonlySet<number>>(new Set())

  const fetchPage = useCallback((): Promise<Paginated<FavoriteItem>> => {
    return listMyFavorites(page, PAGE_SIZE)
  }, [page])

  const { data, loading, error, retry } = useQueryList(fetchPage)

  function handleUnfavorite(item: FavoriteItem): void {
    if (busyId != null) return
    setActionError(null)
    setBusyId(item.id)
    unfavoriteProduct(item.id)
      .then(() => {
        setRemovedIds((prev) => new Set(prev).add(item.id))
      })
      .catch((err: unknown) => {
        if (!isTokenInvalidError(err)) {
          setActionError(errorMessage(err, '取消收藏失败，请稍后重试'))
        }
      })
      .finally(() => {
        setBusyId(null)
      })
  }

  const visibleItems = (data?.items ?? []).filter((item) => !removedIds.has(item.id))

  return (
    <div className="page-container">
      <PageHeader title="我的收藏" description="按收藏时间倒序；已下架 / 已售条目置灰，仍可取消收藏" />

      {actionError && (
        <p className="form-field__error" role="alert">
          {actionError}
        </p>
      )}

      <StateView
        loading={loading}
        error={error}
        onRetry={retry}
        empty={visibleItems.length === 0}
        emptyDescription={
          <span>
            还没有收藏任何商品，
            <Link to="/products">去逛逛</Link>
          </span>
        }
      >
        {data && (
          <>
            <p className="my-favorites__hint" aria-live="polite">
              共 {Math.max(data.total - removedIds.size, 0)} 件收藏
            </p>
            <ul className="product-grid" aria-label="收藏列表">
              {visibleItems.map((item) => (
                <li key={item.id}>
                  <ProductCard
                    product={item}
                    extra={
                      <>
                        <span className="my-favorites__time">
                          收藏于 {formatDateTime(item.favorited_at)}
                        </span>
                        <Button
                          size="small"
                          onClick={() => handleUnfavorite(item)}
                          loading={busyId === item.id}
                          aria-busy={busyId === item.id}
                          aria-label={`取消收藏 ${item.title}`}
                        >
                          取消收藏
                        </Button>
                      </>
                    }
                  />
                </li>
              ))}
            </ul>
            <Pagination
              className="product-list__pagination"
              current={data.page}
              total={Math.max(data.total - removedIds.size, 0)}
              pageSize={data.page_size}
              showSizeChanger={false}
              hideOnSinglePage
              onChange={setPage}
            />
          </>
        )}
      </StateView>
    </div>
  )
}
