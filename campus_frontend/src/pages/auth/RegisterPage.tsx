import { Alert, Button, Input } from 'antd'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { register } from '../../api/auth'
import { ApiError } from '../../api/http'
import { PageHeader } from '../../components/PageHeader'
import { useAuthPhase } from '../../stores/authStore'
import { errorMessage, extractFieldErrors } from '../../utils/apiError'
import {
  validateEmail,
  validateNicknameOptional,
  validatePassword,
  validateStudentNo,
  validateUsername,
} from '../../utils/validators'
import './auth.css'

interface RegisterErrors {
  username?: string
  nickname?: string
  email?: string
  student_no?: string
  password?: string
  confirmPassword?: string
}

type RegisterField = keyof RegisterErrors

/** 契约 RegisterInput 字段顺序，内联错误按此铺回表单 */
const API_FIELDS: RegisterField[] = [
  'username',
  'nickname',
  'email',
  'student_no',
  'password',
]

/**
 * 注册页：五字段（用户名/密码/邮箱/学号/昵称可选）+ 确认密码（仅前端确认）。
 * 客户端预检按批次计划「3.0 字段校验对照表」逐项实现；预检不替代后端复验，
 * 后端 9001 的 data.fields 逐字段内联展示；2001/2002 映射到对应字段；成功回填账号并跳登录。
 */
export function RegisterPage() {
  const usernameId = useId()
  const nicknameId = useId()
  const emailId = useId()
  const studentNoId = useId()
  const passwordId = useId()
  const confirmPasswordId = useId()
  const phase = useAuthPhase()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [nickname, setNickname] = useState('')
  const [email, setEmail] = useState('')
  const [studentNo, setStudentNo] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<RegisterErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 页面入口守卫（与路由层 GuestOnly 双层拦截）
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }

  function validate(): boolean {
    const next: RegisterErrors = {}
    const usernameError = validateUsername(username)
    if (usernameError) next.username = usernameError
    const nicknameError = validateNicknameOptional(nickname.trim())
    if (nicknameError) next.nickname = nicknameError
    const emailError = validateEmail(email)
    if (emailError) next.email = emailError
    const studentNoError = validateStudentNo(studentNo)
    if (studentNoError) next.student_no = studentNoError
    const passwordError = validatePassword(password)
    if (passwordError) next.password = passwordError
    if (confirmPassword !== password) {
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
      await register({
        username: username.trim(),
        password,
        email: email.trim(),
        student_no: studentNo.trim(),
        ...(nickname.trim() !== '' ? { nickname: nickname.trim() } : {}),
      })
      navigate('/login', {
        replace: true,
        state: { notice: '注册成功，请登录', account: username.trim() },
      })
    } catch (error) {
      const fields = extractFieldErrors(error)
      if (fields) {
        const next: RegisterErrors = {}
        for (const field of API_FIELDS) {
          const message = fields[field]
          if (message) next[field] = message
        }
        setErrors(next)
      } else if (error instanceof ApiError && error.code === 2001) {
        setErrors({ username: error.message })
      } else if (error instanceof ApiError && error.code === 2002) {
        setErrors({ student_no: error.message })
      } else {
        setFormError(errorMessage(error, '注册失败，请稍后重试'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-container auth-page">
      <PageHeader title="注册" description="注册后需登录；用户名与学号注册后不可修改" />
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
            aria-describedby={errors.username ? `${usernameId}-error` : `${usernameId}-hint`}
            status={errors.username ? 'error' : undefined}
          />
          {!errors.username && (
            <p id={`${usernameId}-hint`} className="form-field__hint">
              1–32 位，字母开头，仅含字母/数字/下划线
            </p>
          )}
          {errors.username && (
            <p id={`${usernameId}-error`} className="form-field__error" role="alert">
              {errors.username}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={nicknameId} className="form-field__label">
            昵称（可选）
          </label>
          <Input
            id={nicknameId}
            name="nickname"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            autoComplete="nickname"
            aria-invalid={errors.nickname ? true : undefined}
            aria-describedby={errors.nickname ? `${nicknameId}-error` : `${nicknameId}-hint`}
            status={errors.nickname ? 'error' : undefined}
          />
          {!errors.nickname && (
            <p id={`${nicknameId}-hint`} className="form-field__hint">
              留空时默认使用用户名（1–32 字符）
            </p>
          )}
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
          <label htmlFor={studentNoId} className="form-field__label">
            学号
          </label>
          <Input
            id={studentNoId}
            name="student_no"
            value={studentNo}
            onChange={(e) => setStudentNo(e.target.value)}
            required
            aria-required="true"
            aria-invalid={errors.student_no ? true : undefined}
            aria-describedby={errors.student_no ? `${studentNoId}-error` : `${studentNoId}-hint`}
            status={errors.student_no ? 'error' : undefined}
          />
          {!errors.student_no && (
            <p id={`${studentNoId}-hint`} className="form-field__hint">
              1–32 字符；校园认证时须与注册学号完全一致
            </p>
          )}
          {errors.student_no && (
            <p id={`${studentNoId}-error`} className="form-field__error" role="alert">
              {errors.student_no}
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
              8–64 位，须同时包含字母与数字
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
          注册
        </Button>
      </form>
      <p className="auth-form__links">
        已有账号？<Link to="/login">登录</Link>
      </p>
    </div>
  )
}
