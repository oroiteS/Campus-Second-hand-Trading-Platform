import { Button, Input } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase } from '../../stores/authStore'
import './auth.css'

interface LoginErrors {
  account?: string
  password?: string
}

/**
 * 登录页（批次 0 占位）：完整表单无障碍示范——
 * label 关联、aria-required / aria-invalid / aria-describedby、错误 role="alert"。
 * 批次 1 已接入 authStore 真实流程；本页完整登录逻辑随下一提交（feat(auth)）交付。
 */
export function LoginPage() {
  const accountId = useId()
  const passwordId = useId()
  const phase = useAuthPhase()

  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<LoginErrors>({})

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function validate(): boolean {
    const next: LoginErrors = {}
    if (!account.trim()) {
      next.account = '请输入账号'
    }
    if (!password) {
      next.password = '请输入密码'
    } else if (password.length < 8) {
      next.password = '密码长度不得低于 8 位'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validate()) return
    // 真实登录接入前的过渡提示（下一提交交付完整登录页）
    setErrors({ password: '登录通道正在接入真实接口，请稍候' })
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="登录" description="使用校园账号登录平台（接口批次 1 上线，当前为演示登录）" />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
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
              学号或邮箱（字段契约随批次 1 定稿）
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

        <Button type="primary" htmlType="submit" block>
          登录
        </Button>
      </form>
      <p className="auth-form__links">
        还没有账号？<Link to="/register">注册</Link>
        <span aria-hidden="true">·</span>
        <Link to="/forgot-password">忘记密码</Link>
      </p>
    </div>
  )
}
