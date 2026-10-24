import { Alert, Button, Input, Select, Tag } from 'antd'
import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { submitApplication } from '../../api/certification'
import { USE_MOCK } from '../../api/config'
import { getMyApplications } from '../../api/certification'
import { listSchools } from '../../api/schools'
import { PageHeader } from '../../components/PageHeader'
import { StateView } from '../../components/StateView'
import { useAuthStore } from '../../stores/authStore'
import type { AuthApplication, SchoolWithCampuses } from '../../types'
import { useAsyncData } from '../../hooks/useAsyncData'
import { errorMessage, extractFieldErrors, isTokenInvalidError } from '../../utils/apiError'
import { formatDateTime } from '../../utils/format'
import { isInternalPath } from '../../utils/routeState'
import { AUTH_STATUS_TEXT } from '../../utils/statusText'
import {
  validateRealName,
  validateUploadFile,
} from '../../utils/validators'
import './account.css'

interface CertErrors {
  school_id?: string
  campus_id?: string
  real_name?: string
  student_no?: string
  file?: string
}

const STATUS_TAG_COLOR = {
  unverified: 'default',
  pending: 'processing',
  approved: 'success',
  rejected: 'error',
} as const

/**
 * 校园认证页：学校下拉（listSchools）→ 校区级联（multi_campus 必选、单校区隐藏）；
 * student_no 预填注册值且只读（防代认证）；状态区四态互斥、与 auth_status 单一来源一致：
 * unverified 显示表单 / pending 审核中（禁止重复提交）/ rejected 显示驳回原因 + 重提 /
 * approved 完成态；历史申请列表时间倒序 + 状态徽章。
 */
export function CertificationPage() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const schools = useAsyncData(listSchools)
  const applications = useAsyncData(getMyApplications)

  const [submitNotice, setSubmitNotice] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 消费 1004 统一引导（http.ts handleCertificationRequired）写入的 ?from= 回跳参数：
  // 引导走 window.location.assign 整页跳转、无法携带 location.state，故此处按 query
  // 口径消费（改动最小）；仅接受站内路径防外链，且认证页自身不触发 1004 引导，无循环跳转。
  const rawFrom = searchParams.get('from')
  const fromPath = isInternalPath(rawFrom) ? rawFrom : null

  // 页面入口守卫（与路由层 RequireAuth 双层拦截）
  if (!user) {
    return <Navigate to="/login" replace />
  }

  const status = user.auth_status
  const canSubmit = status === 'unverified' || status === 'rejected'

  // rejected：取最新一条 rejected 申请的驳回原因
  const latestRejected = applications.data?.find(
    (item) => item.status === 'rejected',
  )
  const rejectReason =
    status === 'rejected'
      ? (latestRejected?.reject_reason ?? '材料未通过审核，请修改后重新提交')
      : null

  return (
    <div className="page-container">
      <PageHeader
        title="校园认证"
        description="认证通过后才能访问商品交易功能（平台最硬准入线）"
      />

      <StateView
        loading={schools.loading}
        error={schools.error}
        onRetry={schools.reload}
      >
        <p className="account-meta">
          当前状态：
          <Tag color={STATUS_TAG_COLOR[status]}>{AUTH_STATUS_TEXT[status]}</Tag>
        </p>

        {submitNotice && (
          <Alert type="success" showIcon role="status" message={submitNotice} />
        )}
        {submitError && (
          <Alert type="error" showIcon role="alert" message={submitError} />
        )}

        {status === 'pending' && (
          <Alert
            type="info"
            showIcon
            message="认证审核中"
            description="管理员正在审核你的认证材料，审核期间无需重复提交。"
          />
        )}

        {status === 'approved' && (
          <Alert
            type="success"
            showIcon
            message="已通过校园认证"
            description="你可以使用商品发布、浏览与交易等全部学生功能。"
            action={
              fromPath ? (
                <Button size="small" onClick={() => navigate(fromPath)}>
                  返回原页面
                </Button>
              ) : undefined
            }
          />
        )}

        {status === 'rejected' && (
          <Alert
            type="error"
            showIcon
            role="alert"
            message="认证被驳回"
            description={`驳回原因：${rejectReason}。可修改材料后重新提交。`}
          />
        )}

        {canSubmit && user.role !== 'admin' && (
          <CertificationForm
            schools={schools.data ?? []}
            studentNo={user.student_no}
            rejectMode={status === 'rejected'}
            onSubmitted={(application) => {
              setSubmitNotice(
                `认证申请已提交（编号 ${application.id}），请等待管理员审核`,
              )
              setSubmitError(null)
              // 用户 auth_status 同步置 pending（与后端行为一致），表单随之收起
              setUser({ ...user, auth_status: 'pending' })
              applications.reload()
            }}
            onError={(message) => {
              setSubmitError(message)
              setSubmitNotice(null)
            }}
            onClearError={() => setSubmitError(null)}
          />
        )}

        {canSubmit && user.role === 'admin' && (
          <Alert
            type="info"
            showIcon
            message="管理员账号无需校园认证"
            description="管理员不参与校园认证流程，可直接访问管理后台。"
          />
        )}

        <section className="account-panel" aria-labelledby="cert-history-title">
          <h2 id="cert-history-title" className="account-panel__title">
            认证申请历史
          </h2>
          <StateView
            loading={applications.loading}
            error={
              isTokenInvalidError(applications.error) ? null : applications.error
            }
            onRetry={applications.reload}
            empty={(applications.data?.length ?? 0) === 0}
            emptyDescription="暂无认证申请记录"
          >
            <ul className="cert-history">
              {(applications.data ?? []).map((application) => (
                <li key={application.id} className="cert-history__item">
                  <div className="cert-history__head">
                    <Tag color={STATUS_TAG_COLOR[application.status]}>
                      {AUTH_STATUS_TEXT[application.status]}
                    </Tag>
                    <span className="cert-history__school">
                      {application.school.name}
                      {application.campus ? `（${application.campus.name}）` : ''}
                    </span>
                    <span className="cert-history__time">
                      {formatDateTime(application.created_at)}
                    </span>
                  </div>
                  <dl className="cert-history__detail">
                    <div>
                      <dt>申请人</dt>
                      <dd>{application.real_name}</dd>
                    </div>
                    <div>
                      <dt>学号</dt>
                      <dd>{application.student_no}</dd>
                    </div>
                    {application.reviewed_at && (
                      <div>
                        <dt>审核时间</dt>
                        <dd>{formatDateTime(application.reviewed_at)}</dd>
                      </div>
                    )}
                    {application.status === 'rejected' && application.reject_reason && (
                      <div>
                        <dt>驳回原因</dt>
                        <dd>{application.reject_reason}</dd>
                      </div>
                    )}
                  </dl>
                </li>
              ))}
            </ul>
          </StateView>
        </section>
      </StateView>
    </div>
  )
}

interface CertificationFormProps {
  schools: SchoolWithCampuses[]
  studentNo: string
  rejectMode: boolean
  onSubmitted: (application: AuthApplication) => void
  onError: (message: string) => void
  onClearError: () => void
}

function CertificationForm({
  schools,
  studentNo,
  rejectMode,
  onSubmitted,
  onError,
  onClearError,
}: CertificationFormProps) {
  const [schoolId, setSchoolId] = useState<number | null>(null)
  const [campusId, setCampusId] = useState<number | null>(null)
  const [realName, setRealName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [errors, setErrors] = useState<CertErrors>({})
  const [submitting, setSubmitting] = useState(false)

  const selectedSchool = schools.find((school) => school.id === schoolId) ?? null
  const campusOptions =
    selectedSchool?.campuses.map((campus) => ({
      value: campus.id,
      label: campus.name,
    })) ?? []

  // 本地预览 URL 释放
  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl)
      }
    }
  }, [previewUrl])

  function handleSchoolChange(value: number) {
    setSchoolId(value)
    setCampusId(null) // 切换学校重置校区
    setErrors((prev) => ({ ...prev, school_id: undefined, campus_id: undefined }))
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null
    event.target.value = ''
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
      setPreviewUrl(null)
    }
    setFile(selected)
    setErrors((prev) => ({ ...prev, file: undefined }))
    if (selected) {
      const invalid = validateUploadFile(selected, '学生证照片')
      if (invalid) {
        setErrors((prev) => ({ ...prev, file: invalid }))
        return
      }
      setPreviewUrl(URL.createObjectURL(selected))
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onClearError()
    const next: CertErrors = {}
    if (schoolId == null) {
      next.school_id = '请选择学校'
    } else {
      const school = schools.find((item) => item.id === schoolId)
      if (school?.multi_campus && campusId == null) {
        next.campus_id = '多校区学校必须选择校区'
      }
    }
    const realNameError = validateRealName(realName)
    if (realNameError) next.real_name = realNameError
    if (!file) {
      next.file = '请选择学生证照片'
    } else {
      const fileError = validateUploadFile(file, '学生证照片')
      if (fileError) next.file = fileError
    }
    setErrors(next)
    if (Object.keys(next).length > 0 || schoolId == null || !file) return
    setSubmitting(true)
    try {
      const application = await submitApplication({
        school_id: schoolId,
        ...(campusId != null ? { campus_id: campusId } : {}),
        real_name: realName.trim(),
        student_no: studentNo, // 只读预填,防代认证
        file,
      })
      onSubmitted(application)
    } catch (err) {
      const fields = extractFieldErrors(err)
      if (fields) {
        const mapped: CertErrors = {
          school_id: fields.school_id,
          campus_id: fields.campus_id,
          real_name: fields.real_name,
          student_no: fields.student_no,
          file: fields.file,
        }
        if (Object.values(mapped).some((message) => message != null && message !== '')) {
          setErrors(mapped)
        } else {
          // 后端返回未知字段（如 purpose / student_no.0）：无字段可落位时回落表单级提示
          onError(errorMessage(err, '提交失败，请稍后重试'))
        }
      } else if (!isTokenInvalidError(err)) {
        // 9003 状态冲突等表单级反馈
        onError(errorMessage(err, '提交失败，请稍后重试'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="account-panel" aria-labelledby="cert-form-title">
      <h2 id="cert-form-title" className="account-panel__title">
        {rejectMode ? '重新提交认证' : '提交认证申请'}
      </h2>
      <form onSubmit={handleSubmit} noValidate className="account-form">
        <div className="form-field">
          <label htmlFor="cert-school" className="form-field__label">
            学校
          </label>
          <Select
            id="cert-school"
            aria-label="选择学校"
            placeholder="请选择学校"
            options={schools.map((school) => ({
              value: school.id,
              label: school.name,
            }))}
            value={schoolId}
            onChange={handleSchoolChange}
            status={errors.school_id ? 'error' : undefined}
          />
          {errors.school_id && (
            <p className="form-field__error" role="alert">
              {errors.school_id}
            </p>
          )}
        </div>

        {selectedSchool?.multi_campus && (
          <div className="form-field">
            <label htmlFor="cert-campus" className="form-field__label">
              校区
            </label>
            <Select
              id="cert-campus"
              aria-label="选择校区"
              placeholder="请选择校区"
              options={campusOptions}
              value={campusId}
              onChange={(value) => {
                setCampusId(value)
                setErrors((prev) => ({ ...prev, campus_id: undefined }))
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

        <div className="form-field">
          <label htmlFor="cert-real-name" className="form-field__label">
            真实姓名
          </label>
          <Input
            id="cert-real-name"
            name="real_name"
            value={realName}
            onChange={(e) => setRealName(e.target.value)}
            autoComplete="name"
            required
            aria-required="true"
            aria-invalid={errors.real_name ? true : undefined}
            aria-describedby={
              errors.real_name ? 'cert-real-name-error' : 'cert-real-name-hint'
            }
            status={errors.real_name ? 'error' : undefined}
          />
          {!errors.real_name && (
            <p id="cert-real-name-hint" className="form-field__hint">
              须与学生证上的姓名一致（1–32 字符）
            </p>
          )}
          {errors.real_name && (
            <p id="cert-real-name-error" className="form-field__error" role="alert">
              {errors.real_name}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cert-student-no" className="form-field__label">
            学号
          </label>
          <Input
            id="cert-student-no"
            name="student_no"
            value={studentNo}
            readOnly
            aria-readonly="true"
            aria-invalid={errors.student_no ? true : undefined}
            aria-describedby={
              errors.student_no ? 'cert-student-no-error' : 'cert-student-no-hint'
            }
            status={errors.student_no ? 'error' : undefined}
          />
          {errors.student_no ? (
            /* b1 审查建议⑤：后端对该只读字段返 9001 时也内联展示（防御性渲染位） */
            <p id="cert-student-no-error" className="form-field__error" role="alert">
              {errors.student_no}
            </p>
          ) : (
            <p id="cert-student-no-hint" className="form-field__hint">
              预填注册学号且不可修改，防止代他人认证
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cert-file" className="form-field__label">
            学生证照片
          </label>
          <input
            id="cert-file"
            className="avatar-upload__input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            aria-label="选择学生证照片文件（jpg/png/webp，不超过 5MB）"
            aria-describedby="cert-file-hint"
            onChange={handleFileChange}
            disabled={submitting}
          />
          <p id="cert-file-hint" className="form-field__hint">
            支持 jpg / png / webp，不超过 5 MB。
            {USE_MOCK && '示例材料：演示环境可上传任意符合格式的图片。'}
          </p>
          {errors.file && (
            <p className="form-field__error" role="alert">
              {errors.file}
            </p>
          )}
          {previewUrl && (
            <img
              className="cert-preview"
              src={previewUrl}
              alt="学生证照片预览"
              loading="lazy"
              decoding="async"
            />
          )}
        </div>

        <div className="account-form__actions">
          <Button type="primary" htmlType="submit" loading={submitting} aria-busy={submitting}>
            {rejectMode ? '重新提交认证' : '提交认证申请'}
          </Button>
        </div>
      </form>
    </section>
  )
}
