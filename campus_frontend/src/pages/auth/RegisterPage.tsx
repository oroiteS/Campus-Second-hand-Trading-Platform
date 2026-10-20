import { Button, Input } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase } from '../../stores/authStore'
import './auth.css'

interface RegisterErrors {
  nickname?: string
  email?: string
  password?: string
  confirmPassword?: string
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/**
 * 注册页（批次 0 占位）：表单无障碍与客户端预检示范。
 * 注册接口批次 1 上线，提交后展示占位反馈（role="alert"）。
 */
export function RegisterPage() {
  const nicknameId = useId()
  const emailId = useId()
  const passwordId = useId()
  const confirmPasswordId = useId()
  const phase = useAuthPhase()

  const [nickname, setNickname] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<RegisterErrors>({})
  const [notice, setNotice] = useState<string | null>(null)

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function validate(): boolean {
    const next: RegisterErrors = {}
    if (!nickname.trim()) {
      next.nickname = '请输入昵称'
    }
    if (!email.trim()) {
      next.email = '请输入邮箱'
    } else if (!EMAIL_PATTERN.test(email.trim())) {
      next.email = '邮箱格式不正确'
    }
    if (!password) {
      next.password = '请输入密码'
    } else if (password.length < 8 || !/[a-zA-Z]/.test(password) || !/\d/.test(password)) {
      next.password = '密码长度不得低于 8 位且需包含字母与数字'
    }
    if (confirmPassword !== password) {
      next.confirmPassword = '两次输入的密码不一致'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice(null)
    if (!validate()) return
    setNotice('注册通道将于批次 1 开放；演示请直接使用登录页。')
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="注册" description="注册接口批次 1 上线，当前为占位表单演示" />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="form-field">
          <label htmlFor={nicknameId} className="form-field__label">
            昵称
          </label>
          <Input
            id={nicknameId}
            name="nickname"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            autoComplete="nickname"
            required
            aria-required="true"
            aria-invalid={errors.nickname ? true : undefined}
            aria-describedby={errors.nickname ? `${nicknameId}-error` : undefined}
            status={errors.nickname ? 'error' : undefined}
          />
          {errors.nickname && (
            <p id={`${nicknameId}-error`} className="form-field__error" role="alert">
              {errors.nickname}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={emailId} className="form-field__label">
            邮箱
          </label>
          <Input
            id={emailId}
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            aria-required="true"
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? `${emailId}-error` : undefined}
            status={errors.email ? 'error' : undefined}
          />
          {errors.email && (
            <p id={`${emailId}-error`} className="form-field__error" role="alert">
              {errors.email}
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
            autoComplete="new-password"
            required
            aria-required="true"
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={errors.password ? `${passwordId}-error` : `${passwordId}-hint`}
            status={errors.password ? 'error' : undefined}
          />
          {!errors.password && (
            <p id={`${passwordId}-hint`} className="form-field__hint">
              长度不低于 8 位，需包含字母与数字
            </p>
          )}
          {errors.password && (
            <p id={`${passwordId}-error`} className="form-field__error" role="alert">
              {errors.password}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={confirmPasswordId} className="form-field__label">
            确认密码
          </label>
          <Input.Password
            id={confirmPasswordId}
            name="confirmPassword"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
            aria-required="true"
            aria-invalid={errors.confirmPassword ? true : undefined}
            aria-describedby={errors.confirmPassword ? `${confirmPasswordId}-error` : undefined}
            status={errors.confirmPassword ? 'error' : undefined}
          />
          {errors.confirmPassword && (
            <p id={`${confirmPasswordId}-error`} className="form-field__error" role="alert">
              {errors.confirmPassword}
            </p>
          )}
        </div>

        <Button type="primary" htmlType="submit" block>
          注册
        </Button>
      </form>
      {notice && (
        <p className="auth-form__notice" role="alert">
          {notice}
        </p>
      )}
      <p className="auth-form__links">
        已有账号？<Link to="/login">登录</Link>
      </p>
    </div>
  )
}
