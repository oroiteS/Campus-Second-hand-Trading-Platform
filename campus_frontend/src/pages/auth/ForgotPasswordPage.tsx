import { Button, Input } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase } from '../../stores/authStore'
import './auth.css'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** 找回密码页（批次 0 占位）：重置接口批次 1 上线，提交后展示占位反馈 */
export function ForgotPasswordPage() {
  const emailId = useId()
  const phase = useAuthPhase()
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice(null)
    if (!email.trim()) {
      setError('请输入注册邮箱')
      return
    }
    if (!EMAIL_PATTERN.test(email.trim())) {
      setError('邮箱格式不正确')
      return
    }
    setError(null)
    setNotice('找回密码通道将于批次 1 开放，届时可通过邮箱验证码重置。')
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="找回密码" description="重置接口批次 1 上线，当前为占位表单演示" />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="form-field">
          <label htmlFor={emailId} className="form-field__label">
            注册邮箱
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
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${emailId}-error` : `${emailId}-hint`}
            status={error ? 'error' : undefined}
          />
          {!error && (
            <p id={`${emailId}-hint`} className="form-field__hint">
              将向注册邮箱发送验证邮件
            </p>
          )}
          {error && (
            <p id={`${emailId}-error`} className="form-field__error" role="alert">
              {error}
            </p>
          )}
        </div>
        <Button type="primary" htmlType="submit" block>
          发送重置邮件
        </Button>
      </form>
      {notice && (
        <p className="auth-form__notice" role="alert">
          {notice}
        </p>
      )}
      <p className="auth-form__links">
        想起密码了？<Link to="/login">返回登录</Link>
      </p>
    </div>
  )
}
