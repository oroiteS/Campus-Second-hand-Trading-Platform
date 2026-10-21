import { Alert, Button, Input } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { login } from '../../api/auth'
import { USE_MOCK } from '../../api/config'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase, useAuthStore } from '../../stores/authStore'
import { errorMessage } from '../../utils/apiError'
import { readStatePath, readStateString } from '../../utils/routeState'
import { validateAccount, validateRequired } from '../../utils/validators'
import './auth.css'

interface LoginErrors {
  account?: string
  password?: string
}

/** mock 演示账号（VITE_USE_MOCK=true 时展示，便于三态走查） */
const MOCK_HINT_ACCOUNTS = [
  'student01（未认证学生）',
  'student02（已认证学生）',
  'student03（被驳回学生）',
  'admin01（管理员）',
]

/**
 * 登录页：account（用户名或学号）+ password。
 * 成功 → setAuth(access_token, user) → 按 from 参数或角色回首页；
 * 2005 表单级错误、1006 限流提示（含剩余时间语感）、2006 封禁提示，均 role="alert" 可见反馈。
 */
export function LoginPage() {
  const accountId = useId()
  const passwordId = useId()
  const phase = useAuthPhase()
  const navigate = useNavigate()
  const location = useLocation()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [account, setAccount] = useState(() => readStateString(location.state, 'account') ?? '')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<LoginErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [formNotice, setFormNotice] = useState<string | null>(() =>
    readStateString(location.state, 'notice') ?? null,
  )
  const [submitting, setSubmitting] = useState(false)

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function validate(): boolean {
    const next: LoginErrors = {}
    const accountError = validateAccount(account)
    if (accountError) next.account = accountError
    const passwordError = validateRequired(password, '密码')
    if (passwordError) next.password = passwordError
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    setFormNotice(null)
    if (!validate()) return
    setSubmitting(true)
    try {
      const data = await login({ account: account.trim(), password })
      setAuth(data.access_token, data.user)
      const from = readStatePath(location.state, 'from')
      const fallback = data.user.role === 'admin' ? '/admin' : '/'
      navigate(from ?? fallback, { replace: true })
    } catch (error) {
      setFormError(errorMessage(error, '登录失败，请稍后重试'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="登录" description="使用用户名或学号登录校园二手交易平台" />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        {formNotice && (
          <Alert type="success" showIcon role="status" message={formNotice} />
        )}
        {formError && (
          <Alert type="error" showIcon role="alert" message={formError} />
        )}

        <div className="form-field">
          <label htmlFor={accountId} className="form-field__label">
            账号
          </label>
          <Input
            id={accountId}
            name="account"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            autoComplete="username"
            required
            aria-required="true"
            aria-invalid={errors.account ? true : undefined}
            aria-describedby={errors.account ? `${accountId}-error` : `${accountId}-hint`}
            status={errors.account ? 'error' : undefined}
          />
          {!errors.account && (
            <p id={`${accountId}-hint`} className="form-field__hint">
              用户名或学号
            </p>
          )}
          {errors.account && (
            <p id={`${accountId}-error`} className="form-field__error" role="alert">
              {errors.account}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={passwordId} className="form-field__label">
            密码
          </label>
          <Input.Password
            id={passwordId}
            name="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            aria-required="true"
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={errors.password ? `${passwordId}-error` : undefined}
            status={errors.password ? 'error' : undefined}
          />
          {errors.password && (
            <p id={`${passwordId}-error`} className="form-field__error" role="alert">
              {errors.password}
            </p>
          )}
        </div>

        <Button type="primary" htmlType="submit" block loading={submitting} aria-busy={submitting}>
          登录
        </Button>
      </form>

      {USE_MOCK && (
        <p className="auth-form__demo">
          演示账号（密码均为 Pass1234）：{MOCK_HINT_ACCOUNTS.join(' / ')}
        </p>
      )}

      <p className="auth-form__links">
        还没有账号？<Link to="/register">注册</Link>
        <span aria-hidden="true">·</span>
        <Link to="/forgot-password">忘记密码</Link>
      </p>
    </div>
  )
}
