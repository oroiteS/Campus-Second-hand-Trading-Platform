import { Alert, Button, Input, Select } from 'antd'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getProduct, createProduct, updateProduct } from '../../api/products'
import { listCategories } from '../../api/categories'
import { listSchools } from '../../api/schools'
import { ApiError } from '../../api/http'
import { ForbiddenPage } from '../ForbiddenPage'
import { PageHeader } from '../../components/PageHeader'
import { StateView } from '../../components/StateView'
import { ImageUploader, MAX_PRODUCT_IMAGES, type UploadedImage } from '../../components/ImageUploader'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useAuthPhase, useAuthStore } from '../../stores/authStore'
import type {
  ProductCondition,
  ProductCreateInput,
  ProductDetail,
  ProductStatus,
} from '../../types'
import { errorMessage, extractFieldErrors, isTokenInvalidError } from '../../utils/apiError'
import { CONDITION_TEXT } from '../../utils/statusText'
import {
  validateDescription,
  validatePrice,
  validatePriceOptional,
  validateTitle,
} from '../../utils/validators'
import './product.css'

interface PublishErrors {
  title?: string
  description?: string
  price?: string
  original_price?: string
  category_id?: string
  condition?: string
  image_ids?: string
  campus_id?: string
}

const CONDITION_SELECT_OPTIONS: Array<{ label: string; value: ProductCondition }> = (
  ['brand_new', 'as_new', 'excellent', 'good', 'fair'] as const
).map((value) => ({ label: CONDITION_TEXT[value], value }))

/** 编辑态不可编辑状态的前置拦截提示（3001 同文案口径） */
function statusBlockedMessage(status: ProductStatus): string | null {
  if (status === 'trading' || status === 'sold') {
    return `商品当前状态为${
      status === 'trading' ? '交易中' : '已售'
    }，不允许编辑；仅上架或已下架商品可编辑`
  }
  return null
}

/**
 * 发布 / 编辑共用页（/publish 与 /products/:id/edit）：
 * - 表单五字段 + 校区（缺省发布者校区）+ ImageUploader 多图管理；
 * - 编辑态拉详情回显（图集为既有 ImageRef，可删可增，提交全量替换）；
 * - 预检按批次计划 3.0 表（validators 同源）：非法即内联报错不发请求；
 * - 后端 9001 data.fields 逐字段内联（aria-invalid + aria-describedby）；
 * - 编辑 3001（交易中/已售）前置提示 + 提交兜底，附返回详情引导；成功跳详情。
 */
export function ProductPublishPage() {
  const phase = useAuthPhase()
  const location = useLocation()
  const { id } = useParams()

  // 页面入口守卫（与路由层 RequireStudent 双层拦截）
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }
  if (phase === 'admin') {
    return <ForbiddenPage />
  }

  const editId = id != null ? Number(id) : null
  if (editId != null && (!Number.isInteger(editId) || editId <= 0)) {
    return (
      <div className="page-container">
        <p className="form-field__error" role="alert">
          商品 id 无效
        </p>
      </div>
    )
  }

  return <PublishForm key={editId ?? 'create'} editId={editId} />
}

interface PublishFormProps {
  editId: number | null
}

function PublishForm({ editId }: PublishFormProps) {
  const isEdit = editId != null
  const navigate = useNavigate()
  const currentUser = useAuthStore((s) => s.user)

  const categories = useAsyncData(listCategories)
  const schools = useAsyncData(listSchools)

  const [origin, setOrigin] = useState<ProductDetail | null>(null)
  const [originLoading, setOriginLoading] = useState(isEdit)
  const [originError, setOriginError] = useState<string | null>(null)
  const [originTick, setOriginTick] = useState(0)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [price, setPrice] = useState('')
  const [originalPrice, setOriginalPrice] = useState('')
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [condition, setCondition] = useState<ProductCondition | null>(null)
  // 校区预填发布者校区（契约 ProductCreateInput.campus_id 可空、缺省取发布者校区）：
  // 单校区学生无选择器也能以本人校区正常发布，多校区学生可在选择器中改选
  const [campusId, setCampusId] = useState<number | null>(currentUser?.campus?.id ?? null)
  const [images, setImages] = useState<UploadedImage[]>([])

  const [errors, setErrors] = useState<PublishErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [blockedMessage, setBlockedMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 编辑态：拉详情回显（组件按 editId 重挂载；用户身份经 getState 非响应式读取）
  useEffect(() => {
    if (editId == null) return
    let cancelled = false
    const me = useAuthStore.getState().user
    getProduct(editId)
      .then((detail) => {
        if (cancelled) return
        setOrigin(detail)
        setTitle(detail.title)
        setDescription(detail.description)
        setPrice(String(detail.price))
        setOriginalPrice(detail.original_price != null ? String(detail.original_price) : '')
        setCategoryId(detail.category?.id ?? null)
        setCondition(detail.condition)
        setCampusId(detail.campus?.id ?? null)
        setImages(detail.images.map((image) => ({ id: image.id, url: image.url })))
        if (detail.seller == null || detail.seller.id !== me?.id) {
          setBlockedMessage('只能编辑自己发布的商品')
        } else {
          setBlockedMessage(statusBlockedMessage(detail.status))
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.code === 9002) {
          setOriginError('商品不存在、已下架或无权访问')
        } else if (!isTokenInvalidError(err)) {
          setOriginError(errorMessage(err, '商品加载失败，请稍后重试'))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setOriginLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [editId, originTick])

  function retryOrigin(): void {
    setOriginLoading(true)
    setOriginError(null)
    setOriginTick((prev) => prev + 1)
  }

  // 校区选项：本人学校（multi_campus 才显示选择器，与认证页口径一致）
  const mySchool = useMemo(
    () => schools.data?.find((school) => school.id === currentUser?.school?.id) ?? null,
    [schools.data, currentUser?.school?.id],
  )
  const campusOptions =
    mySchool?.campuses.map((campus) => ({ label: campus.name, value: campus.id })) ?? []
  // 校区选择器仅多校区学校渲染；必填校验随之收口（单校区学生不再被无选择器的必填卡死）
  const showCampus = mySchool?.multi_campus === true

  function validateForm(): PublishErrors {
    const next: PublishErrors = {}
    const titleError = validateTitle(title)
    if (titleError) next.title = titleError
    const descriptionError = validateDescription(description)
    if (descriptionError) next.description = descriptionError
    const priceError = validatePrice(price)
    if (priceError) next.price = priceError
    const originalError = validatePriceOptional(originalPrice)
    if (originalError) next.original_price = originalError
    if (categoryId == null) next.category_id = '请选择分类'
    if (condition == null) next.condition = '请选择成色'
    if (showCampus && campusId == null) next.campus_id = '请选择校区'
    if (images.length < 1) {
      next.image_ids = `请至少上传 1 张商品图片`
    } else if (images.length > MAX_PRODUCT_IMAGES) {
      next.image_ids = `最多上传 ${MAX_PRODUCT_IMAGES} 张商品图片`
    }
    return next
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (blockedMessage || submitting) return
    setFormError(null)
    // 预检（3.0 对照表同源）：非法输入拦截后不发请求
    const next = validateForm()
    setErrors(next)
    if (Object.keys(next).length > 0) return
    if (categoryId == null || condition == null) return // 预检已覆盖，此处仅为类型收窄

    const body: ProductCreateInput = {
      title: title.trim(),
      description,
      price: Number(price),
      original_price: originalPrice.trim() === '' ? null : Number(originalPrice),
      category_id: categoryId,
      condition,
      campus_id: campusId,
      image_ids: images.map((image) => image.id),
    }

    setSubmitting(true)
    try {
      const detail = isEdit && editId != null ? await updateProduct(editId, body) : await createProduct(body)
      navigate(`/products/${detail.id}`, { replace: true })
    } catch (err) {
      const fields = extractFieldErrors(err)
      if (fields) {
        // 9001 data.fields 逐字段内联
        setErrors({
          title: fields.title,
          description: fields.description,
          price: fields.price,
          original_price: fields.original_price,
          category_id: fields.category_id,
          condition: fields.condition,
          campus_id: fields.campus_id,
          image_ids: fields.image_ids,
        })
      } else if (err instanceof ApiError && err.code === 3001) {
        setFormError(err.message)
        setBlockedMessage(err.message)
      } else if (!isTokenInvalidError(err)) {
        setFormError(errorMessage(err, isEdit ? '保存失败，请稍后重试' : '发布失败，请稍后重试'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (isEdit) {
    return (
      <div className="page-container">
        <PageHeader
          title="编辑商品"
          description="全量字段替换；图集可删除既有图片或追加新图，提交后按新顺序替换"
        />
        <StateView
          loading={originLoading}
          error={originError}
          onRetry={retryOrigin}
          empty={!originLoading && !originError && origin == null}
          emptyDescription="商品不存在或无权访问"
        >
          <PublishFormBody
            isEdit
            blockedMessage={blockedMessage}
            originId={editId}
            title={title}
            description={description}
            price={price}
            originalPrice={originalPrice}
            categoryId={categoryId}
            condition={condition}
            campusId={campusId}
            images={images}
            errors={errors}
            formError={formError}
            submitting={submitting}
            categoryOptions={(categories.data ?? []).map((c) => ({ label: c.name, value: c.id }))}
            categoryLoading={categories.loading}
            campusOptions={campusOptions}
            showCampus={showCampus}
            onTitle={setTitle}
            onDescription={setDescription}
            onPrice={setPrice}
            onOriginalPrice={setOriginalPrice}
            onCategory={setCategoryId}
            onCondition={setCondition}
            onCampus={setCampusId}
            onImages={setImages}
            onSubmit={handleSubmit}
            onClearFieldError={(field) => setErrors((prev) => ({ ...prev, [field]: undefined }))}
          />
        </StateView>
      </div>
    )
  }

  return (
    <div className="page-container">
      <PageHeader title="发布商品" description="发布即上架；图片 1–9 张，首图为封面" />
      <PublishFormBody
        isEdit={false}
        blockedMessage={null}
        originId={null}
        title={title}
        description={description}
        price={price}
        originalPrice={originalPrice}
        categoryId={categoryId}
        condition={condition}
        campusId={campusId}
        images={images}
        errors={errors}
        formError={formError}
        submitting={submitting}
        categoryOptions={(categories.data ?? []).map((c) => ({ label: c.name, value: c.id }))}
        categoryLoading={categories.loading}
        campusOptions={campusOptions}
        showCampus={showCampus}
        onTitle={setTitle}
        onDescription={setDescription}
        onPrice={setPrice}
        onOriginalPrice={setOriginalPrice}
        onCategory={setCategoryId}
        onCondition={setCondition}
        onCampus={setCampusId}
        onImages={setImages}
        onSubmit={handleSubmit}
        onClearFieldError={(field) => setErrors((prev) => ({ ...prev, [field]: undefined }))}
      />
    </div>
  )
}

interface PublishFormBodyProps {
  isEdit: boolean
  blockedMessage: string | null
  originId: number | null
  title: string
  description: string
  price: string
  originalPrice: string
  categoryId: number | null
  condition: ProductCondition | null
  campusId: number | null
  images: UploadedImage[]
  errors: PublishErrors
  formError: string | null
  submitting: boolean
  categoryOptions: Array<{ label: string; value: number }>
  categoryLoading: boolean
  campusOptions: Array<{ label: string; value: number }>
  showCampus: boolean
  onTitle: (value: string) => void
  onDescription: (value: string) => void
  onPrice: (value: string) => void
  onOriginalPrice: (value: string) => void
  onCategory: (value: number) => void
  onCondition: (value: ProductCondition) => void
  onCampus: (value: number) => void
  onImages: (images: UploadedImage[]) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onClearFieldError: (field: keyof PublishErrors) => void
}

/** 表单体（发布/编辑共用渲染，受控展示态由父组件持有） */
function PublishFormBody(props: PublishFormBodyProps) {
  const {
    isEdit,
    blockedMessage,
    originId,
    errors,
    formError,
    submitting,
    categoryOptions,
    categoryLoading,
    campusOptions,
    showCampus,
  } = props

  return (
    <>
      {formError && (
        <Alert type="error" showIcon role="alert" message={formError} className="publish-alert" />
      )}
      {blockedMessage && (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message="当前状态不可编辑"
          description={
            <span>
              {blockedMessage}
              {originId != null && (
                <>
                  {' '}
                  <Link to={`/products/${originId}`}>返回商品详情</Link>
                </>
              )}
            </span>
          }
          className="publish-alert"
        />
      )}
      <form className="account-form publish-form" onSubmit={props.onSubmit} noValidate>
        <div className="form-field">
          <label htmlFor="publish-title" className="form-field__label">
            标题
          </label>
          <Input
            id="publish-title"
            name="title"
            value={props.title}
            onChange={(e) => {
              props.onTitle(e.target.value)
              props.onClearFieldError('title')
            }}
            required
            aria-required="true"
            aria-invalid={errors.title ? true : undefined}
            aria-describedby={errors.title ? 'publish-title-error' : 'publish-title-hint'}
            status={errors.title ? 'error' : undefined}
            autoComplete="off"
          />
          {!errors.title && (
            <p id="publish-title-hint" className="form-field__hint">
              1–50 个字符
            </p>
          )}
          {errors.title && (
            <p id="publish-title-error" className="form-field__error" role="alert">
              {errors.title}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="publish-description" className="form-field__label">
            描述
          </label>
          <Input.TextArea
            id="publish-description"
            name="description"
            value={props.description}
            onChange={(e) => {
              props.onDescription(e.target.value)
              props.onClearFieldError('description')
            }}
            required
            aria-required="true"
            aria-invalid={errors.description ? true : undefined}
            aria-describedby={
              errors.description ? 'publish-description-error' : 'publish-description-hint'
            }
            status={errors.description ? 'error' : undefined}
            rows={5}
          />
          {!errors.description && (
            <p id="publish-description-hint" className="form-field__hint">
              1–2000 个字符，成色细节、使用时长与瑕疵说明越清楚越容易出手
            </p>
          )}
          {errors.description && (
            <p id="publish-description-error" className="form-field__error" role="alert">
              {errors.description}
            </p>
          )}
        </div>

        <div className="publish-form__price-row">
          <div className="form-field">
            <label htmlFor="publish-price" className="form-field__label">
              售价（元）
            </label>
            <Input
              id="publish-price"
              name="price"
              inputMode="decimal"
              value={props.price}
              onChange={(e) => {
                props.onPrice(e.target.value)
                props.onClearFieldError('price')
              }}
              required
              aria-required="true"
              aria-invalid={errors.price ? true : undefined}
              aria-describedby={errors.price ? 'publish-price-error' : 'publish-price-hint'}
              status={errors.price ? 'error' : undefined}
            />
            {!errors.price && (
              <p id="publish-price-hint" className="form-field__hint">
                0.01–99999.99，最多两位小数
              </p>
            )}
            {errors.price && (
              <p id="publish-price-error" className="form-field__error" role="alert">
                {errors.price}
              </p>
            )}
          </div>
          <div className="form-field">
            <label htmlFor="publish-original-price" className="form-field__label">
              原价（元，选填）
            </label>
            <Input
              id="publish-original-price"
              name="original_price"
              inputMode="decimal"
              value={props.originalPrice}
              onChange={(e) => {
                props.onOriginalPrice(e.target.value)
                props.onClearFieldError('original_price')
              }}
              aria-invalid={errors.original_price ? true : undefined}
              aria-describedby={
                errors.original_price ? 'publish-original-price-error' : undefined
              }
              status={errors.original_price ? 'error' : undefined}
            />
            {errors.original_price && (
              <p id="publish-original-price-error" className="form-field__error" role="alert">
                {errors.original_price}
              </p>
            )}
          </div>
        </div>

        <div className="publish-form__select-row">
          <div className="form-field">
            <label htmlFor="publish-category" className="form-field__label">
              分类
            </label>
            <Select
              id="publish-category"
              placeholder={categoryLoading ? '分类加载中…' : '请选择分类'}
              options={categoryOptions}
              value={props.categoryId}
              onChange={(value) => {
                props.onCategory(value)
                props.onClearFieldError('category_id')
              }}
              status={errors.category_id ? 'error' : undefined}
            />
            {errors.category_id && (
              <p className="form-field__error" role="alert">
                {errors.category_id}
              </p>
            )}
          </div>
          <div className="form-field">
            <label htmlFor="publish-condition" className="form-field__label">
              成色
            </label>
            <Select
              id="publish-condition"
              placeholder="请选择成色"
              options={CONDITION_SELECT_OPTIONS}
              value={props.condition}
              onChange={(value) => {
                props.onCondition(value)
                props.onClearFieldError('condition')
              }}
              status={errors.condition ? 'error' : undefined}
            />
            {errors.condition && (
              <p className="form-field__error" role="alert">
                {errors.condition}
              </p>
            )}
          </div>
          {showCampus && (
            <div className="form-field">
              <label htmlFor="publish-campus" className="form-field__label">
                校区
              </label>
              <Select
                id="publish-campus"
                placeholder="请选择校区"
                options={campusOptions}
                value={props.campusId}
                onChange={(value) => {
                  props.onCampus(value)
                  props.onClearFieldError('campus_id')
                }}
                status={errors.campus_id ? 'error' : undefined}
              />
              {errors.campus_id && (
                <p className="form-field__error" role="alert">
                  {errors.campus_id}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="form-field">
          <span className="form-field__label" id="publish-images-label">
            商品图片
          </span>
          <ImageUploader images={props.images} onChange={props.onImages} disabled={submitting} />
          {errors.image_ids && (
            <p className="form-field__error" role="alert">
              {errors.image_ids}
            </p>
          )}
        </div>

        <div className="account-form__actions">
          <Button type="primary" htmlType="submit" loading={submitting} aria-busy={submitting}>
            {isEdit ? '保存修改' : '发布'}
          </Button>
          {originId != null && <Link to={`/products/${originId}`}>返回详情</Link>}
        </div>
      </form>
    </>
  )
}
