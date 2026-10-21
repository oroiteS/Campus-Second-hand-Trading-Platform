import { Alert, Button, Input, Modal, Tag } from 'antd'
import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { logout } from '../../api/auth'
import { USE_MOCK } from '../../api/config'
import { ApiError } from '../../api/http'
import { changePassword, getMe, updateMe, uploadAvatar } from '../../api/users'
import { PageHeader } from '../../components/PageHeader'
import { StateView } from '../../components/StateView'
import { useAuthStore } from '../../stores/authStore'
import type { ProfileUpdateInput, UserProfile } from '../../types'
import { useAsyncData } from '../../hooks/useAsyncData'
import {
  errorMessage,
  extractFieldErrors,
  isTokenInvalidError,
} from '../../utils/apiError'
import { formatDateTime } from '../../utils/format'
import { AUTH_STATUS_TEXT, ROLE_TEXT } from '../../utils/statusText'
import {
  validateEmail,
  validateLength,
  validatePassword,
  validatePhoneOptional,
  validateRequired,
  validateUploadFile,
} from '../../utils/validators'
import './account.css'

interface ProfileEditErrors {
  nickname?: string
  email?: string
  phone?: string
}

interface PasswordErrors {
  old_password?: string
  new_password?: string
  confirmPassword?: string
}

const STATUS_TAG_COLOR = {
  unverified: 'default',
  pending: 'processing',
  approved: 'success',
  rejected: 'error',
} as const

/**
 * 个人中心：资料卡（展示名/学校/校区/认证徽章/头像）+ 资料编辑
 * （nickname/email/phone，仅提交变更字段；phone 非法预检拦截不发请求，空串 = 清除）
 * + 改密弹窗（2003 内联到原密码字段）+ 头像上传（预检类型/5MB、本地预览）+ 登出。
 * 未认证用户同样可达（RequireAuth 已覆盖）。
 */
export function ProfilePage() {
  const storeUser = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const navigate = useNavigate()
  const { data: freshUser, loading, error, reload } = useAsyncData(getMe)

  // 页面入口守卫（与路由层 RequireAuth 双层拦截）
  if (!storeUser) {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="page-container">
      <PageHeader title="个人中心" description="维护个人资料、头像与登录密码" />
      <StateView loading={loading} error={error} onRetry={reload}>
        {freshUser && (
          <ProfilePanels
            key={freshUser.id}
            profile={freshUser}
            onProfileSync={setUser}
            onReload={reload}
            onClearAuth={clearAuth}
            onNavigateLogin={() => navigate('/login', { replace: true })}
          />
        )}
      </StateView>
    </div>
  )
}

interface ProfilePanelsProps {
  profile: UserProfile
  onProfileSync: (user: UserProfile) => void
  onReload: () => void
  onClearAuth: () => void
  onNavigateLogin: () => void
}

function ProfilePanels({ profile, onProfileSync, onReload, onClearAuth, onNavigateLogin }: ProfilePanelsProps) {
  const [editErrors, setEditErrors] = useState<ProfileEditErrors>({})
  const [editNotice, setEditNotice] = useState<string | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [nicknameDraft, setNicknameDraft] = useState(profile.nickname)
  const [emailDraft, setEmailDraft] = useState(profile.email)
  const [phoneDraft, setPhoneDraft] = useState(profile.phone ?? '')

  const [passwordOpen, setPasswordOpen] = useState(false)
  const [passwordNotice, setPasswordNotice] = useState<string | null>(null)

  const [avatarUploading, setAvatarUploading] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null)

  const [loggingOut, setLoggingOut] = useState(false)

  // 头像本地预览 URL 释放
  useEffect(() => {
    return () => {
      if (avatarPreview) {
        URL.revokeObjectURL(avatarPreview)
      }
    }
  }, [avatarPreview])

  async function handleProfileSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setEditNotice(null)
    setEditError(null)
    // 预检（3.0 对照表）：非法输入仅内联报错，不发请求
    const next: ProfileEditErrors = {}
    const nicknameError = validateLength(nicknameDraft, '昵称', 1, 32)
    if (nicknameError) next.nickname = nicknameError
    const emailError = validateEmail(emailDraft)
    if (emailError) next.email = emailError
    const phoneError = validatePhoneOptional(phoneDraft)
    if (phoneError) next.phone = phoneError
    setEditErrors(next)
    if (Object.keys(next).length > 0) return

    // 仅提交变更字段；phone 输入空串而原值存在 → 提交空串表示清除
    const body: ProfileUpdateInput = {}
    if (nicknameDraft !== profile.nickname) body.nickname = nicknameDraft
    if (emailDraft !== profile.email) body.email = emailDraft
    if (phoneDraft !== (profile.phone ?? '')) body.phone = phoneDraft
    if (Object.keys(body).length === 0) {
      setEditNotice('未修改任何字段')
      return
    }
    setSaving(true)
    try {
      const updated = await updateMe(body)
      onProfileSync(updated)
      onReload()
      setEditNotice('资料已更新')
    } catch (err) {
      const fields = extractFieldErrors(err)
      if (fields) {
        setEditErrors({ nickname: fields.nickname, email: fields.email, phone: fields.phone })
      } else if (!isTokenInvalidError(err)) {
        setEditError(errorMessage(err, '保存失败，请稍后重试'))
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleAvatarChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setAvatarError(null)
    // 客户端预检类型/大小：非法不发请求
    const invalid = validateUploadFile(file, '头像')
    if (invalid) {
      setAvatarError(invalid)
      return
    }
    const previewUrl = URL.createObjectURL(file)
    setAvatarPreview(previewUrl)
    setAvatarUploading(true)
    try {
      const updated = await uploadAvatar(file)
      onProfileSync(updated)
      onReload()
    } catch (err) {
      if (!isTokenInvalidError(err)) {
        setAvatarError(errorMessage(err, '头像上传失败，请稍后重试'))
      }
    } finally {
      setAvatarUploading(false)
      URL.revokeObjectURL(previewUrl)
      setAvatarPreview(null)
    }
  }

  return (
    <div className="account-grid">
      <section className="account-panel profile-card-panel" aria-labelledby="profile-card-title">
        <h2 id="profile-card-title" className="account-panel__title">
          我的资料
        </h2>
        <div className="profile-card">
          {avatarPreview ? (
            <img
              className="profile-avatar"
              src={avatarPreview}
              alt="新头像预览"
              width={64}
              height={64}
              decoding="async"
            />
          ) : profile.avatar ? (
            <img
              className="profile-avatar"
              src={profile.avatar.url}
              alt={`${profile.nickname}的头像`}
              width={64}
              height={64}
              loading="lazy"
              decoding="async"
            />
          ) : (
            <span className="profile-avatar profile-avatar--fallback" aria-hidden="true">
              {profile.nickname.slice(0, 1)}
            </span>
          )}
          <div className="profile-card__main">
            <p className="profile-card__display-name">{profile.display_name}</p>
            <p className="profile-card__sub">
              <Tag>{ROLE_TEXT[profile.role]}</Tag>
              <Tag color={STATUS_TAG_COLOR[profile.auth_status]}>
                {AUTH_STATUS_TEXT[profile.auth_status]}
              </Tag>
            </p>
          </div>
        </div>
        <dl className="profile-fields">
          <div className="profile-fields__row">
            <dt>用户名</dt>
            <dd>{profile.username}</dd>
          </div>
          <div className="profile-fields__row">
            <dt>学号</dt>
            <dd>{profile.student_no}</dd>
          </div>
          <div className="profile-fields__row">
            <dt>学校</dt>
            <dd>{profile.school?.name ?? '未认证'}</dd>
          </div>
          <div className="profile-fields__row">
            <dt>校区</dt>
            <dd>{profile.campus?.name ?? '—'}</dd>
          </div>
          <div className="profile-fields__row">
            <dt>信誉分</dt>
            <dd>{profile.credit_score == null ? '暂无' : profile.credit_score}</dd>
          </div>
          <div className="profile-fields__row">
            <dt>注册时间</dt>
            <dd>{formatDateTime(profile.created_at)}</dd>
          </div>
        </dl>

        <div className="avatar-upload">
          <label htmlFor="avatar-input" className="form-field__label">
            更换头像
          </label>
          <input
            id="avatar-input"
            className="avatar-upload__input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            aria-label="选择头像图片文件（jpg/png/webp，不超过 5MB）"
            aria-describedby="avatar-input-hint"
            onChange={handleAvatarChange}
            disabled={avatarUploading}
          />
          <p id="avatar-input-hint" className="form-field__hint">
            支持 jpg / png / webp，不超过 5 MB{avatarUploading ? '；正在上传…' : ''}
          </p>
          {avatarError && (
            <p className="form-field__error" role="alert">
              {avatarError}
            </p>
          )}
        </div>
      </section>

      <section className="account-panel" aria-labelledby="profile-edit-title">
        <h2 id="profile-edit-title" className="account-panel__title">
          编辑资料
        </h2>
        {editNotice && (
          <Alert type="success" showIcon role="status" message={editNotice} closable />
        )}
        {editError && (
          <Alert type="error" showIcon role="alert" message={editError} />
        )}
        <form onSubmit={handleProfileSave} noValidate className="account-form">
          <div className="form-field">
            <label htmlFor="nickname-input" className="form-field__label">
              昵称
            </label>
            <Input
              id="nickname-input"
              name="nickname"
              value={nicknameDraft}
              onChange={(e) => setNicknameDraft(e.target.value)}
              autoComplete="nickname"
              aria-invalid={editErrors.nickname ? true : undefined}
              aria-describedby={editErrors.nickname ? 'nickname-input-error' : 'nickname-input-hint'}
              status={editErrors.nickname ? 'error' : undefined}
            />
            {!editErrors.nickname && (
              <p id="nickname-input-hint" className="form-field__hint">
                1–32 字符
              </p>
            )}
            {editErrors.nickname && (
              <p id="nickname-input-error" className="form-field__error" role="alert">
                {editErrors.nickname}
              </p>
            )}
          </div>

          <div className="form-field">
            <label htmlFor="email-input" className="form-field__label">
              邮箱
            </label>
            <Input
              id="email-input"
              name="email"
              type="email"
              value={emailDraft}
              onChange={(e) => setEmailDraft(e.target.value)}
              autoComplete="email"
              aria-invalid={editErrors.email ? true : undefined}
              aria-describedby={editErrors.email ? 'email-input-error' : undefined}
              status={editErrors.email ? 'error' : undefined}
            />
            {editErrors.email && (
              <p id="email-input-error" className="form-field__error" role="alert">
                {editErrors.email}
              </p>
            )}
          </div>

          <div className="form-field">
            <label htmlFor="phone-input" className="form-field__label">
              手机号
            </label>
            <Input
              id="phone-input"
              name="phone"
              type="tel"
              value={phoneDraft}
              onChange={(e) => setPhoneDraft(e.target.value)}
              autoComplete="tel"
              inputMode="numeric"
              maxLength={11}
              aria-invalid={editErrors.phone ? true : undefined}
              aria-describedby={editErrors.phone ? 'phone-input-error' : 'phone-input-hint'}
              status={editErrors.phone ? 'error' : undefined}
            />
            {!editErrors.phone && (
              <p id="phone-input-hint" className="form-field__hint">
                1 开头的 11 位纯数字；清空并保存即清除手机号
              </p>
            )}
            {editErrors.phone && (
              <p id="phone-input-error" className="form-field__error" role="alert">
                {editErrors.phone}
              </p>
            )}
          </div>

          <div className="account-form__actions">
            <Button type="primary" htmlType="submit" loading={saving} aria-busy={saving}>
              保存修改
            </Button>
            <Button onClick={() => setPasswordOpen(true)}>修改密码</Button>
            <Button
              danger
              onClick={handleLogout}
              loading={loggingOut}
              aria-busy={loggingOut}
            >
              退出登录
            </Button>
          </div>
        </form>
      </section>

      <ChangePasswordModal
        open={passwordOpen}
        onClose={() => setPasswordOpen(false)}
        onSuccess={(message) => {
          setPasswordOpen(false)
          setPasswordNotice(message)
        }}
      />
      {passwordNotice && (
        <Alert type="success" showIcon role="status" message={passwordNotice} closable />
      )}
      {USE_MOCK && (
        <p className="account-mock-hint">
          mock 模式：当前会话由 mock 登录数据承担，资料修改仅存于内存会话。
        </p>
      )}
    </div>
  )

  async function handleLogout() {
    setLoggingOut(true)
    try {
      // 令牌类失败已由 http 层清令牌并引导；其余失败也保证本地登出
      await logout()
    } catch {
      // 登出接口异常不阻塞本地退出
    }
    onClearAuth()
    onNavigateLogin()
  }
}

interface ChangePasswordModalProps {
  open: boolean
  onClose: () => void
  onSuccess: (message: string) => void
}

/** 改密弹窗：2003 原密码错误内联到该字段；新密码预检同对照表 */
function ChangePasswordModal({ open, onClose, onSuccess }: ChangePasswordModalProps) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<PasswordErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function resetFields() {
    setOldPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setErrors({})
    setFormError(null)
  }

  function handleClose() {
    resetFields()
    onClose()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const next: PasswordErrors = {}
    const oldError = validateRequired(oldPassword, '原密码')
    if (oldError) next.old_password = oldError
    const newError = validatePassword(newPassword)
    if (newError) next.new_password = newError
    if (confirmPassword !== newPassword) {
      next.confirmPassword = '两次输入的密码不一致'
    }
    setErrors(next)
    if (Object.keys(next).length > 0) return
    setSaving(true)
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword })
      onSuccess('密码已修改，下次登录请使用新密码')
    } catch (err) {
      const fields = extractFieldErrors(err)
      if (fields) {
        setErrors({
          old_password: fields.old_password,
          new_password: fields.new_password,
        })
      } else if (err instanceof ApiError && err.code === 2003) {
        // 原密码错误内联到该字段
        setErrors({ old_password: err.message })
      } else if (!isTokenInvalidError(err)) {
        setFormError(errorMessage(err, '修改失败，请稍后重试'))
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="修改密码"
      open={open}
      onCancel={handleClose}
      footer={null}
      destroyOnHidden
      aria-modal="true"
    >
      <form onSubmit={handleSubmit} noValidate className="account-form">
        {formError && (
          <Alert type="error" showIcon role="alert" message={formError} />
        )}
        <div className="form-field">
          <label htmlFor="old-password-input" className="form-field__label">
            原密码
          </label>
          <Input.Password
            id="old-password-input"
            name="old_password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            autoComplete="current-password"
            required
            aria-required="true"
            aria-invalid={errors.old_password ? true : undefined}
            aria-describedby={errors.old_password ? 'old-password-error' : undefined}
            status={errors.old_password ? 'error' : undefined}
          />
          {errors.old_password && (
            <p id="old-password-error" className="form-field__error" role="alert">
              {errors.old_password}
            </p>
          )}
        </div>
        <div className="form-field">
          <label htmlFor="new-password-input" className="form-field__label">
            新密码
          </label>
          <Input.Password
            id="new-password-input"
            name="new_password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            required
            aria-required="true"
            aria-invalid={errors.new_password ? true : undefined}
            aria-describedby={
              errors.new_password ? 'new-password-error' : 'new-password-hint'
            }
            status={errors.new_password ? 'error' : undefined}
          />
          {!errors.new_password && (
            <p id="new-password-hint" className="form-field__hint">
              8–64 位，须同时包含字母与数字
            </p>
          )}
          {errors.new_password && (
            <p id="new-password-error" className="form-field__error" role="alert">
              {errors.new_password}
            </p>
          )}
        </div>
        <div className="form-field">
          <label htmlFor="confirm-password-input" className="form-field__label">
            确认新密码
          </label>
          <Input.Password
            id="confirm-password-input"
            name="confirmPassword"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
            aria-required="true"
            aria-invalid={errors.confirmPassword ? true : undefined}
            aria-describedby={errors.confirmPassword ? 'confirm-password-error' : undefined}
            status={errors.confirmPassword ? 'error' : undefined}
          />
          {errors.confirmPassword && (
            <p id="confirm-password-error" className="form-field__error" role="alert">
              {errors.confirmPassword}
            </p>
          )}
        </div>
        <div className="account-form__actions">
          <Button type="primary" htmlType="submit" loading={saving} aria-busy={saving}>
            确认修改
          </Button>
          <Button onClick={handleClose}>取消</Button>
        </div>
      </form>
    </Modal>
  )
}
