import { Alert, Button, Input, Segmented } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { resetPassword } from '../../api/auth'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase } from '../../stores/authStore'
import { errorMessage, extractFieldErrors } from '../../utils/apiError'
import {
  validateEmail,
  validatePassword,
  validateRequired,
  validateStudentNo,
} from '../../utils/validators'
import './auth.css'

type ResetChannel = 'student_no' | 'email'

const CHANNEL_OPTIONS: { value: ResetChannel; label: string }[] = [
  { value: 'student_no', label: '学号' },
  { value: 'email', label: '邮箱' },
]

interface ResetErrors {
  username?: string
  reset_value?: string
  new_password?: string
  confirmPassword?: string
}

/**
 * 找回密码页：用户名 + 渠道（学号/邮箱）+ 凭证值 + 新密码（预检同对照表）。
 * 2004 不泄露存在性——用户名不存在与凭证不匹配返回同一提示；成功跳登录。
 */
export function ForgotPasswordPage() {
  const usernameId = useId()
  const resetValueId = useId()
  const newPasswordId = useId()
  const confirmPasswordId = useId()
  const phase = useAuthPhase()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [channel, setChannel] = useState<ResetChannel>('student_no')
  const [resetValue, setResetValue] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<ResetErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function validateResetValue(value: string): string | null {
    return channel === 'email' ? validateEmail(value) : validateStudentNo(value)
  }

  function validate(): boolean {
    const next: ResetErrors = {}
    const usernameError = validateRequired(username, '用户名')
    if (usernameError) next.username = usernameError
    const resetValueError = validateResetValue(resetValue)
    if (resetValueError) next.reset_value = resetValueError
    const newPasswordError = validatePassword(newPassword)
    if (newPasswordError) next.new_password = newPasswordError
    if (confirmPassword !== newPassword) {
      next.confirmPassword = '两次输入的密码不一致'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    if (!validate()) return
    setSubmitting(true)
    try {
      await resetPassword({
        username: username.trim(),
        reset_channel: channel,
        reset_value: resetValue.trim(),
        new_password: newPassword,
      })
      navigate('/login', {
        replace: true,
        state: { notice: '密码已重置，请使用新密码登录' },
      })
    } catch (error) {
      const fields = extractFieldErrors(error)
      if (fields) {
        setErrors({
          username: fields.username,
          reset_value: fields.reset_value ?? fields.reset_channel,
          new_password: fields.new_password,
        })
      } else {
        // 2004：用户名不存在与凭证不匹配同码同文案，不泄露存在性（防探测）
        setFormError(errorMessage(error, '重置失败，请稍后重试'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="找回密码" description="通过注册学号或邮箱核验身份后重置密码" />
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <Alert type="error" showIcon role="alert" message={formError} />
        )}

        <div className="form-field">
          <label htmlFor={usernameId} className="form-field__label">
            用户名
          </label>
          <Input
            id={usernameId}
            name="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            aria-required="true"
            aria-invalid={errors.username ? true : undefined}
            aria-describedby={errors.username ? `${usernameId}-error` : undefined}
            status={errors.username ? 'error' : undefined}
          />
          {errors.username && (
            <p id={`${usernameId}-error`} className="form-field__error" role="alert">
              {errors.username}
            </p>
          )}
        </div>

        <div className="form-field">
          <span className="form-field__label" id="reset-channel-label">
            重置渠道
          </span>
          <Segmented
            aria-label="选择重置凭证渠道"
            options={CHANNEL_OPTIONS}
            value={channel}
            onChange={(value) => {
              if (value === 'student_no' || value === 'email') {
                setChannel(value)
                setResetValue('')
                setErrors((prev) => ({ ...prev, reset_value: undefined }))
              }
            }}
          />
        </div>

        <div className="form-field">
          <label htmlFor={resetValueId} className="form-field__label">
            {channel === 'email' ? '注册邮箱' : '注册学号'}
          </label>
          <Input
            id={resetValueId}
            name="reset_value"
            type={channel === 'email' ? 'email' : 'text'}
            value={resetValue}
            onChange={(e) => setResetValue(e.target.value)}
            required
            aria-required="true"
            aria-invalid={errors.reset_value ? true : undefined}
            aria-describedby={errors.reset_value ? `${resetValueId}-error` : `${resetValueId}-hint`}
            status={errors.reset_value ? 'error' : undefined}
          />
          {!errors.reset_value && (
            <p id={`${resetValueId}-hint`} className="form-field__hint">
              {channel === 'email'
                ? '须与注册时填写的邮箱一致'
                : '须与注册时填写的学号完全一致'}
            </p>
          )}
          {errors.reset_value && (
            <p id={`${resetValueId}-error`} className="form-field__error" role="alert">
              {errors.reset_value}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={newPasswordId} className="form-field__label">
            新密码
          </label>
          <Input.Password
            id={newPasswordId}
            name="new_password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            required
            aria-required="true"
            aria-invalid={errors.new_password ? true : undefined}
            aria-describedby={
              errors.new_password ? `${newPasswordId}-error` : `${newPasswordId}-hint`
            }
            status={errors.new_password ? 'error' : undefined}
          />
          {!errors.new_password && (
            <p id={`${newPasswordId}-hint`} className="form-field__hint">
              8–64 位，须同时包含字母与数字
            </p>
          )}
          {errors.new_password && (
            <p id={`${newPasswordId}-error`} className="form-field__error" role="alert">
              {errors.new_password}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={confirmPasswordId} className="form-field__label">
            确认新密码
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
            aria-describedby={
              errors.confirmPassword ? `${confirmPasswordId}-error` : undefined
            }
            status={errors.confirmPassword ? 'error' : undefined}
          />
          {errors.confirmPassword && (
            <p id={`${confirmPasswordId}-error`} className="form-field__error" role="alert">
              {errors.confirmPassword}
            </p>
          )}
        </div>

        <Button type="primary" htmlType="submit" block loading={submitting} aria-busy={submitting}>
          重置密码
        </Button>
      </form>
      <p className="auth-form__links">
        想起密码了？<Link to="/login">返回登录</Link>
      </p>
    </div>
  )
}
