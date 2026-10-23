import { Input, Segmented, Select } from 'antd'
import { listCategories } from '../api/categories'
import { useAsyncData } from '../hooks/useAsyncData'
import type { ProductCondition, ProductListQuery } from '../types'
import { CONDITION_TEXT } from '../utils/statusText'
import './FilterBar.css'

/** 筛选值（列表/搜索共用；价格以字符串暂存，提交前由 validators 预检） */
export interface FilterValues {
  categoryId: number | null
  condition: ProductCondition | null
  priceMin: string
  priceMax: string
}

export type SortValue = NonNullable<ProductListQuery['sort']>

const SORT_OPTIONS: Array<{ label: string; value: SortValue }> = [
  { label: '最新', value: 'newest' },
  { label: '价格从低到高', value: 'price_asc' },
  { label: '价格从高到低', value: 'price_desc' },
]

const CONDITION_OPTIONS: Array<{ label: string; value: ProductCondition }> = (
  ['brand_new', 'as_new', 'excellent', 'good', 'fair'] as const
).map((value) => ({ label: CONDITION_TEXT[value], value }))

export interface FilterPriceErrors {
  min?: string
  max?: string
  range?: string
}

interface FilterBarProps {
  values: FilterValues
  /** 受控：变更即回调（含清除） */
  onChange: (patch: Partial<FilterValues>) => void
  /** 排序（列表专用；搜索页按相似度序不传） */
  sort?: SortValue
  onSortChange?: (sort: SortValue) => void
  /** 价格区间预检错误（页面侧 validators 产出，内联展示） */
  priceErrors?: FilterPriceErrors
  /** id 前缀：列表/搜索两页共用组件时保证表单控件 id 唯一 */
  idPrefix: string
}

/**
 * 列表/搜索共用筛选条：分类下拉（listCategories 缓存于组件级 state）、
 * 成色 5 档、价格区间双输入、排序（列表专用）。
 * 受控组件，变更即回调；预检错误由页面传入内联展示（role="alert"）。
 */
export function FilterBar({
  values,
  onChange,
  sort,
  onSortChange,
  priceErrors = {},
  idPrefix,
}: FilterBarProps) {
  const categories = useAsyncData(listCategories)
  const categoryOptions = (categories.data ?? []).map((category) => ({
    label: category.name,
    value: category.id,
  }))

  return (
    <div className="filter-bar">
      <div className="filter-bar__field">
        <label htmlFor={`${idPrefix}-category`} className="filter-bar__label">
          分类
        </label>
        <Select
          id={`${idPrefix}-category`}
          placeholder={categories.error ? '分类加载失败' : '全部分类'}
          allowClear
          options={categoryOptions}
          value={values.categoryId}
          onChange={(value) => onChange({ categoryId: value ?? null })}
          disabled={categories.loading || categories.error != null}
          status={categories.error ? 'error' : undefined}
        />
        {categories.error && (
          <p className="form-field__error" role="alert">
            {categories.error}
          </p>
        )}
      </div>

      <div className="filter-bar__field">
        <label htmlFor={`${idPrefix}-condition`} className="filter-bar__label">
          成色
        </label>
        <Select
          id={`${idPrefix}-condition`}
          placeholder="全部成色"
          allowClear
          options={CONDITION_OPTIONS}
          value={values.condition}
          onChange={(value) => onChange({ condition: value ?? null })}
        />
      </div>

      <div className="filter-bar__field filter-bar__field--price">
        <span className="filter-bar__label" id={`${idPrefix}-price-label`}>
          价格区间（元）
        </span>
        <div className="filter-bar__price-inputs">
          <Input
            id={`${idPrefix}-price-min`}
            inputMode="decimal"
            placeholder="最低"
            value={values.priceMin}
            onChange={(e) => onChange({ priceMin: e.target.value })}
            aria-labelledby={`${idPrefix}-price-label`}
            aria-invalid={priceErrors.min || priceErrors.range ? true : undefined}
            aria-describedby={
              priceErrors.min || priceErrors.range ? `${idPrefix}-price-error` : undefined
            }
            status={priceErrors.min || priceErrors.range ? 'error' : undefined}
          />
          <span aria-hidden="true">–</span>
          <Input
            id={`${idPrefix}-price-max`}
            inputMode="decimal"
            placeholder="最高"
            value={values.priceMax}
            onChange={(e) => onChange({ priceMax: e.target.value })}
            aria-labelledby={`${idPrefix}-price-label`}
            aria-invalid={priceErrors.max || priceErrors.range ? true : undefined}
            aria-describedby={
              priceErrors.max || priceErrors.range ? `${idPrefix}-price-error` : undefined
            }
            status={priceErrors.max || priceErrors.range ? 'error' : undefined}
          />
        </div>
        {(priceErrors.min || priceErrors.max || priceErrors.range) && (
          <p id={`${idPrefix}-price-error`} className="form-field__error" role="alert">
            {priceErrors.min ?? priceErrors.max ?? priceErrors.range}
          </p>
        )}
      </div>

      {onSortChange && sort != null && (
        <div className="filter-bar__field filter-bar__field--sort">
          <span className="filter-bar__label" id={`${idPrefix}-sort-label`}>
            排序
          </span>
          <Segmented
            id={`${idPrefix}-sort`}
            options={SORT_OPTIONS}
            value={sort}
            onChange={(value) => onSortChange(value as SortValue)}
            aria-labelledby={`${idPrefix}-sort-label`}
          />
        </div>
      )}
    </div>
  )
}
