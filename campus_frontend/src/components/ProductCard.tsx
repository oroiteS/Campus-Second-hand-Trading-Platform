import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ProductSummary } from '../types'
import { formatPrice } from '../utils/format'
import { CONDITION_TEXT, PRODUCT_STATUS_TEXT } from '../utils/statusText'
import './ProductCard.css'

interface ProductCardProps {
  product: ProductSummary
  /** 行内操作区（我的商品 / 收藏列表）；渲染在整卡链接之外，避免交互嵌套 */
  extra?: ReactNode
  /**
   * 是否渲染为可点击链接（缺省 true）。
   * 非在售条目（已下架 / 交易中 / 已售）在收藏、我的商品等场景传 false 渲染为静态卡：
   * 契约下这些状态对当前查看者不可见（sold 无人可见、trading 仅双方），点入必然 404。
   */
  linkable?: boolean
}

/**
 * 商品概要卡：首页宫格 / 列表 / 搜索 / 我的商品 / 收藏共用。
 * - 在售整卡为链接（键盘可达）；非在售按 linkable 渲染静态卡，只保留 extra 操作；
 * - 封面 `loading="lazy" decoding="async"` + 非空 alt = 标题；
 * - 划线原价对比、成色徽章（5 档中文映射）、收藏数、状态徽章（非 on_sale 置灰变体）。
 */
export function ProductCard({ product, extra, linkable = true }: ProductCardProps) {
  const onSale = product.status === 'on_sale'
  const content = (
    <>
      <div className="product-card__cover">
        {product.cover ? (
          <img
            src={product.cover.url}
            alt={product.title}
            loading="lazy"
            decoding="async"
          />
        ) : (
          <span className="product-card__cover-fallback" aria-hidden="true">
            暂无图片
          </span>
        )}
        {!onSale && (
          <span className="product-card__status-badge">
            {PRODUCT_STATUS_TEXT[product.status]}
          </span>
        )}
      </div>
      <div className="product-card__body">
        <h3 className="product-card__title">{product.title}</h3>
        <p className="product-card__price">
          <span className="product-card__price-now">{formatPrice(product.price)}</span>
          {product.original_price != null && product.original_price > product.price && (
            <s className="product-card__price-origin">
              {formatPrice(product.original_price)}
            </s>
          )}
        </p>
        <p className="product-card__meta">
          <span className="product-card__condition">{CONDITION_TEXT[product.condition]}</span>
          {product.campus && (
            <span className="product-card__campus">{product.campus.name}</span>
          )}
          <span className="product-card__favorites">收藏 {product.favorite_count}</span>
        </p>
      </div>
    </>
  )

  return (
    <article className={`product-card${onSale ? '' : ' product-card--inactive'}`}>
      {linkable ? (
        <Link
          to={`/products/${product.id}`}
          className="product-card__link"
          aria-label={`查看商品详情：${product.title}`}
        >
          {content}
        </Link>
      ) : (
        <div className="product-card__link product-card__link--static">{content}</div>
      )}
      {extra && <div className="product-card__extra">{extra}</div>}
    </article>
  )
}
