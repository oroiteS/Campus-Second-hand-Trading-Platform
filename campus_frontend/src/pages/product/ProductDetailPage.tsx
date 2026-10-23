import { Button, Carousel, Result, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { changeProductStatus, getProduct } from '../../api/products'
import { favoriteProduct, unfavoriteProduct } from '../../api/favorites'
import { ApiError } from '../../api/http'
import { PageHeader } from '../../components/PageHeader'
import { StateView } from '../../components/StateView'
import { useAuthPhase, useAuthStore } from '../../stores/authStore'
import type { ProductDetail } from '../../types'
import { errorMessage, isTokenInvalidError } from '../../utils/apiError'
import { formatDateTime, formatPrice } from '../../utils/format'
import { CONDITION_TEXT, PRODUCT_STATUS_TEXT } from '../../utils/statusText'
import './product.css'

/**
 * 商品详情页：
 * - 图片轮播（alt = 标题 + 序号）；价格/划线价/成色/校区/浏览量/发布时间；
 * - 卖家卡片（UserSummary 纯展示不跳转——用户主页 b3）；信誉分 null →「暂无」；
 * - 收藏按钮：乐观更新 + 失败回滚（含 9003/3001 文案），aria-pressed 表达开关态；
 * - 卖家本人视角：编辑 / 上架·下架快捷入口（trading/sold 无操作入口）；
 * - 404（9002 防探测）与通用错误可重试分开呈现；描述按纯文本渲染。
 */
export function ProductDetailPage() {
  const phase = useAuthPhase()
  const location = useLocation()
  const { id } = useParams()

  // 页面入口守卫（与路由层 RequireVerified 双层拦截）
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }

  const productId = Number(id)
  if (!Number.isInteger(productId) || productId <= 0) {
    return (
      <div className="page-container">
        <Result status="404" title="404" subTitle="商品不存在或无权访问" />
      </div>
    )
  }

  // key = productId：路由内切换商品时整组件重挂载，状态零残留
  return <ProductDetail key={productId} productId={productId} />
}

function ProductDetail({ productId }: { productId: number }) {
  const navigate = useNavigate()
  const currentUser = useAuthStore((s) => s.user)

  const [detail, setDetail] = useState<ProductDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [favoriteBusy, setFavoriteBusy] = useState(false)
  const [favoriteNotice, setFavoriteNotice] = useState<string | null>(null)
  /** 上下架回执：success 区分文案语气（成功走中性/成功样式，失败走错误样式） */
  const [statusNotice, setStatusNotice] = useState<{ text: string; success: boolean } | null>(
    null,
  )
  const [statusBusy, setStatusBusy] = useState(false)

  // 首次加载：初始 loading 已为 true，effect 内仅异步落盘（组件按 productId 重挂载）
  useEffect(() => {
    let cancelled = false
    getProduct(productId)
      .then((data) => {
        if (cancelled) return
        setDetail(data)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.code === 9002) {
          setNotFound(true)
        } else if (!isTokenInvalidError(err)) {
          setError(errorMessage(err, '商品加载失败，请稍后重试'))
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
  }, [productId])

  /** 收藏开关：乐观更新，失败（含 9003/3001）精确回滚 UI 状态与计数；非在售直接拦截（3001 前置） */
  function handleToggleFavorite(): void {
    if (!detail || favoriteBusy || detail.status !== 'on_sale') return
    const prevFavorited = detail.is_favorited
    const prevCount = detail.favorite_count
    const nextFavorited = !prevFavorited
    // 乐观更新：立即翻转
    setDetail({
      ...detail,
      is_favorited: nextFavorited,
      favorite_count: Math.max(0, prevCount + (nextFavorited ? 1 : -1)),
    })
    setFavoriteNotice(null)
    setFavoriteBusy(true)
    const request = nextFavorited
      ? favoriteProduct(detail.id)
      : unfavoriteProduct(detail.id)
    request
      .then((result) => {
        // 服务端权威值落地（favorited + favorite_count）
        setDetail((prev) =>
          prev
            ? { ...prev, is_favorited: result.favorited, favorite_count: result.favorite_count }
            : prev,
        )
      })
      .catch((err: unknown) => {
        // 回滚：UI 状态与计数恢复一致
        setDetail((prev) =>
          prev ? { ...prev, is_favorited: prevFavorited, favorite_count: prevCount } : prev,
        )
        if (err instanceof ApiError && err.code === 9003) {
          setFavoriteNotice('操作未生效：已收藏该商品，请刷新查看最新状态')
        } else if (!isTokenInvalidError(err)) {
          setFavoriteNotice(errorMessage(err, '收藏操作失败，请稍后重试'))
        }
      })
      .finally(() => {
        setFavoriteBusy(false)
      })
  }

  /** 卖家快捷上下架（3001/3002 文案来自服务端 message） */
  function handleToggleStatus(): void {
    if (!detail || statusBusy) return
    const target = detail.status === 'on_sale' ? 'off_sale' : 'on_sale'
    setStatusNotice(null)
    setStatusBusy(true)
    changeProductStatus(detail.id, target)
      .then((summary) => {
        setDetail((prev) => (prev ? { ...prev, status: summary.status } : prev))
        setStatusNotice({
          text: target === 'on_sale' ? '商品已重新上架' : '商品已下架，列表与搜索中将不可见',
          success: true,
        })
      })
      .catch((err: unknown) => {
        if (!isTokenInvalidError(err)) {
          setStatusNotice({ text: errorMessage(err, '状态更新失败，请稍后重试'), success: false })
        }
      })
      .finally(() => {
        setStatusBusy(false)
      })
  }

  function retryLoad(): void {
    setLoading(true)
    setNotFound(false)
    setError(null)
    getProduct(productId)
      .then((data) => {
        setDetail(data)
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.code === 9002) {
          setNotFound(true)
        } else if (!isTokenInvalidError(err)) {
          setError(errorMessage(err, '商品加载失败，请稍后重试'))
        }
      })
      .finally(() => {
        setLoading(false)
      })
  }

  if (notFound) {
    return (
      <div className="page-container">
        <Result
          status="404"
          title="404"
          subTitle="商品不存在、已下架或无权访问"
          extra={
            <Button type="primary" onClick={() => navigate('/products', { replace: true })}>
              去商品列表
            </Button>
          }
        />
      </div>
    )
  }

  const isOwner =
    detail?.seller != null && currentUser != null && detail.seller.id === currentUser.id
  const canManage = isOwner && (detail?.status === 'on_sale' || detail?.status === 'off_sale')
  const showFavorite = currentUser != null && currentUser.role !== 'admin'

  return (
    <div className="page-container">
      <PageHeader title="商品详情" />
      <StateView
        loading={loading}
        error={error}
        onRetry={retryLoad}
        empty={!loading && !error && detail == null}
        emptyDescription="商品不存在或无权访问"
      >
        {detail && (
          <div className="product-detail">
            <div>
              <div className="product-detail__gallery">
                <Carousel dots>
                  {detail.images.map((image, index) => (
                    <div key={image.id}>
                      <img
                        src={image.url}
                        alt={`${detail.title} 图 ${index + 1}`}
                        loading="lazy"
                        decoding="async"
                      />
                    </div>
                  ))}
                </Carousel>
                <p className="product-detail__gallery-count">
                  共 {detail.images.length} 张图（顺序即卖家展示顺序）
                </p>
              </div>
            </div>

            <div className="product-detail__main">
              <h2 className="product-detail__title">{detail.title}</h2>
              <p className="product-detail__price-row">
                <span className="product-detail__price">{formatPrice(detail.price)}</span>
                {detail.original_price != null && detail.original_price > detail.price && (
                  <s className="product-detail__price-origin">
                    {formatPrice(detail.original_price)}
                  </s>
                )}
              </p>
              <div className="product-detail__tags">
                <Tag color="processing">{CONDITION_TEXT[detail.condition]}</Tag>
                <Tag color={detail.status === 'on_sale' ? 'success' : 'default'}>
                  {PRODUCT_STATUS_TEXT[detail.status]}
                </Tag>
                {detail.category && <Tag>{detail.category.name}</Tag>}
              </div>
              <dl className="product-detail__facts">
                <div>
                  <dt>校区</dt>
                  <dd>{detail.campus?.name ?? '—'}</dd>
                </div>
                <div>
                  <dt>浏览量</dt>
                  <dd>{detail.view_count}</dd>
                </div>
                <div>
                  <dt>收藏数</dt>
                  <dd>{detail.favorite_count}</dd>
                </div>
                <div>
                  <dt>发布时间</dt>
                  <dd>{formatDateTime(detail.created_at)}</dd>
                </div>
                <div>
                  <dt>最近更新</dt>
                  <dd>{formatDateTime(detail.updated_at)}</dd>
                </div>
              </dl>

              {showFavorite && (
                <div className="product-detail__actions">
                  <Button
                    type={detail.is_favorited ? 'default' : 'primary'}
                    onClick={handleToggleFavorite}
                    loading={favoriteBusy}
                    aria-busy={favoriteBusy}
                    aria-pressed={detail.is_favorited}
                    disabled={detail.status !== 'on_sale'}
                    title={
                      detail.status !== 'on_sale'
                        ? `商品当前状态为${PRODUCT_STATUS_TEXT[detail.status]}，仅上架商品可收藏`
                        : undefined
                    }
                  >
                    {detail.is_favorited ? '取消收藏' : '收藏'}
                  </Button>
                  {favoriteNotice && (
                    <p className="form-field__error" role="alert">
                      {favoriteNotice}
                    </p>
                  )}
                </div>
              )}

              {isOwner && (
                <div className="product-detail__owner-bar">
                  <span className="product-detail__seller-sub">这是你发布的商品：</span>
                  {canManage && (
                    <>
                      <Link to={`/products/${detail.id}/edit`}>编辑</Link>
                      <Button size="small" onClick={handleToggleStatus} loading={statusBusy}>
                        {detail.status === 'on_sale' ? '下架' : '重新上架'}
                      </Button>
                    </>
                  )}
                  {statusNotice && (
                    <p
                      className={
                        statusNotice.success ? 'form-field__success' : 'form-field__error'
                      }
                      role="status"
                    >
                      {statusNotice.text}
                    </p>
                  )}
                </div>
              )}

              {detail.seller && (
                <div className="product-detail__seller">
                  {detail.seller.avatar ? (
                    <img
                      className="product-detail__seller-avatar"
                      src={detail.seller.avatar.url}
                      alt={`${detail.seller.nickname}的头像`}
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <span className="product-detail__seller-fallback" aria-hidden="true">
                      {detail.seller.nickname.slice(0, 1)}
                    </span>
                  )}
                  <div className="product-detail__seller-info">
                    <p className="product-detail__seller-name">{detail.seller.display_name}</p>
                    <p className="product-detail__seller-sub">
                      信誉分：
                      {detail.seller.credit_score == null
                        ? '暂无'
                        : detail.seller.credit_score.toFixed(2)}
                    </p>
                  </div>
                </div>
              )}
            </div>

            <section className="product-detail__section" aria-labelledby="detail-desc-heading">
              <h2 id="detail-desc-heading">商品描述</h2>
              {/* 纯文本渲染（white-space: pre-wrap），不使用 dangerouslySetInnerHTML */}
              <p className="product-detail__description">{detail.description}</p>
            </section>
          </div>
        )}
      </StateView>
    </div>
  )
}
