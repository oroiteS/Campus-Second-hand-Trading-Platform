import { Alert, Button, Modal, Pagination, Tabs } from 'antd'
import { useCallback, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { changeProductStatus, deleteProduct, listMyProducts } from '../../api/products'
import { PageHeader } from '../../components/PageHeader'
import { ProductCard } from '../../components/ProductCard'
import { StateView } from '../../components/StateView'
import { useQueryList } from '../../hooks/useQueryList'
import { useAuthPhase } from '../../stores/authStore'
import type { Paginated, ProductStatus, ProductSummary } from '../../types'
import { errorMessage, isTokenInvalidError } from '../../utils/apiError'
import './product.css'

const PAGE_SIZE = 20

/** 状态 tab（全部 = 契约缺省：除 deleted 外全部） */
const STATUS_TABS: Array<{ key: 'all' | ProductStatus; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'on_sale', label: '在售' },
  { key: 'off_sale', label: '已下架' },
  { key: 'sold', label: '已售' },
  { key: 'trading', label: '交易中' },
]

/**
 * 我的商品：状态 tab + 卡片网格 + 行内操作。
 * - 状态机：编辑 / 上下架 / 删除 仅 on_sale / off_sale 提供（sold/trading 无入口）；
 * - 上下架 3002（强制下架）等错误文案经 Alert 可见；操作成功后列表就地刷新；
 * - 删除二次确认 Modal（危险操作不自动聚焦确认键：焦点落在取消键，关闭还原触发元素）。
 */
export function MyProductsPage() {
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

  return <MyProducts />
}

function MyProducts() {
  const [statusFilter, setStatusFilter] = useState<'all' | ProductStatus>('all')
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ProductSummary | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchPage = useCallback((): Promise<Paginated<ProductSummary>> => {
    return listMyProducts({
      ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
      page,
      page_size: PAGE_SIZE,
    })
  }, [statusFilter, page])

  const { data, loading, fetching, error, retry } = useQueryList(fetchPage)

  function handleTabChange(key: string): void {
    setStatusFilter(key as 'all' | ProductStatus)
    setPage(1)
    setActionError(null)
    setActionNotice(null)
  }

  function refreshAfterAction(): void {
    retry()
  }

  function handleToggleStatus(item: ProductSummary): void {
    if (busyId != null) return
    const target = item.status === 'on_sale' ? 'off_sale' : 'on_sale'
    setActionError(null)
    setActionNotice(null)
    setBusyId(item.id)
    changeProductStatus(item.id, target)
      .then((summary) => {
        setActionNotice(
          summary.status === 'on_sale' ? '商品已重新上架' : '商品已下架，列表与搜索中将不可见',
        )
        refreshAfterAction()
      })
      .catch((err: unknown) => {
        // 3002（强制下架）/ 3001 文案直接来自服务端 message
        if (!isTokenInvalidError(err)) {
          setActionError(errorMessage(err, '状态更新失败，请稍后重试'))
        }
      })
      .finally(() => {
        setBusyId(null)
      })
  }

  function handleDelete(): void {
    if (deleteTarget == null || deleting) return
    setDeleting(true)
    setActionError(null)
    deleteProduct(deleteTarget.id)
      .then(() => {
        setDeleteTarget(null)
        setActionNotice('商品已删除')
        refreshAfterAction()
      })
      .catch((err: unknown) => {
        if (!isTokenInvalidError(err)) {
          setActionError(errorMessage(err, '删除失败，请稍后重试'))
          setDeleteTarget(null)
        }
      })
      .finally(() => {
        setDeleting(false)
      })
  }

  return (
    <div className="page-container">
      <PageHeader title="我的商品" description="管理我发布的商品：编辑、上下架与删除" />

      <Tabs
        className="my-products__tabs"
        activeKey={statusFilter}
        onChange={handleTabChange}
        items={STATUS_TABS.map((tab) => ({ key: tab.key, label: tab.label }))}
      />

      {actionNotice && (
        <Alert type="success" showIcon role="status" message={actionNotice} closable />
      )}
      {actionError && (
        <Alert type="error" showIcon role="alert" message={actionError} closable />
      )}

      <StateView
        loading={loading}
        error={error}
        onRetry={retry}
        empty={(data?.items.length ?? 0) === 0 && !fetching}
        emptyDescription={
          statusFilter === 'all' ? '还没有发布过商品，去发布第一件吧' : '该状态下暂无商品'
        }
      >
        {data && (
          <>
            <p className="product-list__meta" aria-live="polite">
              共 {data.total} 件商品{fetching ? ' · 更新中…' : ''}
              {statusFilter === 'all' && (
                <Link to="/publish" className="my-products__publish-link">
                  发布新商品
                </Link>
              )}
            </p>
            <ul
              className="product-grid"
              aria-label="我的商品列表"
              aria-busy={fetching || undefined}
            >
              {data.items.map((item) => {
                const manageable = item.status === 'on_sale' || item.status === 'off_sale'
                return (
                  <li key={item.id}>
                    <ProductCard
                      product={item}
                      linkable={item.status === 'on_sale'}
                      extra={
                        manageable ? (
                          <>
                            <Link to={`/products/${item.id}/edit`}>编辑</Link>
                            <Button
                              size="small"
                              onClick={() => handleToggleStatus(item)}
                              loading={busyId === item.id}
                              aria-busy={busyId === item.id}
                            >
                              {item.status === 'on_sale' ? '下架' : '重新上架'}
                            </Button>
                            <Button size="small" danger onClick={() => setDeleteTarget(item)}>
                              删除
                            </Button>
                          </>
                        ) : (
                          <span className="product-card__campus">
                            {item.status === 'sold' ? '已售出，不可操作' : '交易中，不可操作'}
                          </span>
                        )
                      }
                    />
                  </li>
                )
              })}
            </ul>
            <Pagination
              className="product-list__pagination"
              current={data.page}
              total={data.total}
              pageSize={data.page_size}
              showSizeChanger={false}
              hideOnSinglePage
              onChange={setPage}
            />
          </>
        )}
      </StateView>

      <Modal
        title="确认删除商品"
        open={deleteTarget != null}
        onOk={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        cancelButtonProps={{ autoFocus: true }}
        confirmLoading={deleting}
        focusTriggerAfterClose
      >
        <p>
          确定删除「{deleteTarget?.title}」吗？删除后商品不可再展示，图片与收藏记录将保留但不可见。
        </p>
      </Modal>
    </div>
  )
}
