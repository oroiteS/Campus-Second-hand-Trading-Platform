import dayjs from 'dayjs'
import type { ProfileUpdateInput, UserProfile, UserSummary } from '../../types'
import { useAuthStore } from '../../stores/authStore'
import { delay } from '../../utils/delay'
import {
  validateEmail,
  validateLength,
  validatePassword,
  validatePhoneOptional,
  validateUploadFile,
} from '../../utils/validators'
import { ApiError, handleCertificationRequired, handleTokenInvalid } from '../http'

/**
 * mock 会话：内存态的「当前登录用户」。
 * mock 登录成功时由 mock/auth 写入；页面刷新后内存丢失，由 getMockCurrentUser
 * 从 authStore 持久化登录态惰性恢复（对齐真实后端「凭持久化令牌重建会话」的刷新体验）。
 */
let currentUser: UserProfile | null = null

export function mockSetSession(profile: UserProfile): void {
  currentUser = profile
}

/** 登出时清除内存会话，与 authStore 清令牌保持一致 */
export function mockClearSession(): void {
  currentUser = null
}

export function getMockCurrentUser(): UserProfile | null {
  if (!currentUser) {
    // persist 恢复的登录态（token+user 齐备）才等价重建会话
    const { token, user } = useAuthStore.getState()
    if (token && user) {
      currentUser = cloneProfile(user)
    }
  }
  return currentUser
}

/**
 * 会话缺失统一兜底：与 http 层令牌失效引导同源——清令牌并引导重新登录（非游客页整页跳转），
 * 再抛 1001 供调用链感知。避免 mock 直接 throw ApiError 绕过拦截器导致错误墙死局
 * （GuestOnly 因持久化令牌仍在而放行 /login 之外的路径，用户无法自行恢复）。
 */
function sessionMissing(): never {
  handleTokenInvalid()
  throw new ApiError(1001, '令牌缺失或无效', null)
}

/** 深拷贝用户资料（含嵌套可空对象），避免 mock 内部状态被外部改动 */
export function cloneProfile(profile: UserProfile): UserProfile {
  return {
    ...profile,
    avatar: profile.avatar ? { ...profile.avatar } : null,
    school: profile.school ? { ...profile.school } : null,
    campus: profile.campus ? { ...profile.campus } : null,
  }
}

/** 展示名规则（FR-USR-10）：approved 后「昵称-学校(校区)」，多校区带括号；未认证为昵称 */
export function displayNameOf(profile: UserProfile): string {
  if (profile.auth_status !== 'approved' || !profile.school) {
    return profile.nickname
  }
  return profile.campus
    ? `${profile.nickname}-${profile.school.name}(${profile.campus.name})`
    : `${profile.nickname}-${profile.school.name}`
}

/** ISO 8601（+08:00）当前时间，与契约时间约定一致 */
export function nowIso(): string {
  return dayjs().format('YYYY-MM-DDTHH:mm:ssZ')
}

function requireSession(): UserProfile {
  return getMockCurrentUser() ?? sessionMissing()
}

/** 供其他 mock 模块获取当前会话；缺失时同样走「清令牌 + 引导登录」兜底，不静默 */
export function requireMockCurrentUser(): UserProfile {
  return requireSession()
}

/**
 * 商品域准入（契约 403/1004，AC-02 最硬准入线）：会话用户须已通过校园认证
 * （approved；管理员按契约总则恒 approved）。未认证 → 统一引导认证页
 * （与 http 拦截器同源，防循环：游客页/认证页本身不触发）并抛 1004 供页面反馈。
 */
export function requireVerifiedSession(): UserProfile {
  const user = requireSession()
  if (user.auth_status !== 'approved') {
    handleCertificationRequired()
    throw new ApiError(1004, '请先完成校园认证', null)
  }
  return user
}

/** UserProfile → 契约 UserSummary 概要（商品池卖家 / 详情卖家卡片） */
export function toUserSummary(profile: UserProfile): UserSummary {
  return {
    id: profile.id,
    display_name: profile.display_name,
    nickname: profile.nickname,
    ...(profile.avatar ? { avatar: { ...profile.avatar } } : {}),
    credit_score: profile.credit_score ?? null,
    auth_status: profile.auth_status,
    role: profile.role,
  }
}

/** GET /api/users/me：当前登录用户完整资料 */
export function mockGetMe(): Promise<UserProfile> {
  return delay(300).then(() => cloneProfile(requireSession()))
}

/**
 * PUT /api/users/me：仅更新请求体中出现的字段；
 * phone 空串 = 清除（置 null）；展示名按认证状态联动重算（AC-04）。
 * 模拟后端 9001 复验（与 utils/validators 同源），含 phone 非法样例。
 */
export function mockUpdateMe(body: ProfileUpdateInput): Promise<UserProfile> {
  return delay(400).then(() => {
    const user = requireSession()
    const fields: Record<string, string> = {}
    if ('nickname' in body) {
      const error = validateLength(body.nickname ?? '', '昵称', 1, 32)
      if (error) fields.nickname = error
    }
    if ('email' in body) {
      const error = validateEmail(body.email ?? '')
      if (error) fields.email = error
    }
    if ('phone' in body) {
      const error = validatePhoneOptional(body.phone ?? '')
      if (error) fields.phone = error
    }
    if (Object.keys(fields).length > 0) {
      throw new ApiError(9001, '参数校验失败', { fields })
    }
    if ('nickname' in body && body.nickname !== undefined) {
      user.nickname = body.nickname
    }
    if ('email' in body && body.email !== undefined) {
      user.email = body.email
    }
    if ('phone' in body) {
      user.phone = body.phone === '' || body.phone == null ? null : body.phone
    }
    user.display_name = displayNameOf(user)
    return cloneProfile(user)
  })
}

/** PUT /api/users/me/password：校验原密码后更新 mock 账号密码（后续登录用新密码） */
export function mockChangePassword(oldPassword: string, newPassword: string): Promise<void> {
  return delay(400).then(() => {
    const user = requireSession()
    const passwordError = validatePassword(newPassword)
    if (passwordError) {
      throw new ApiError(9001, '参数校验失败', { fields: { new_password: passwordError } })
    }
    const account = requireMockAccount(user.id)
    if (account.password !== oldPassword) {
      throw new ApiError(2003, '原密码错误', null)
    }
    account.password = newPassword
  })
}

let nextImageIdSeed = 43

/** 生成 mock 图片 id，url 一律为契约 ImageRef 形态（同源相对路径） */
export function nextImageId(): number {
  nextImageIdSeed += 1
  return nextImageIdSeed
}

/** POST /api/users/me/avatar：文件预检（类型/大小）→ 更新 avatar 字段 */
export function mockUploadAvatar(file: File): Promise<UserProfile> {
  return delay(500).then(() => {
    const user = requireSession()
    const fileError = validateUploadFile(file, '头像')
    if (fileError) {
      throw new ApiError(9001, '参数校验失败', { fields: { file: fileError } })
    }
    const id = nextImageId()
    user.avatar = { id, url: `/api/images/${id}` }
    return cloneProfile(user)
  })
}

// ---- 与 mock/auth 的账号仓库衔接（避免循环依赖：auth → users 单向） ----

export interface MockAccount {
  profile: UserProfile
  /** mock 明文密码仅存内存演示登录校验，真实后端为 bcrypt 哈希（NFR-05） */
  password: string
}

export const MOCK_ACCOUNTS: MockAccount[] = []

export function requireMockAccount(userId: number): MockAccount {
  const account = MOCK_ACCOUNTS.find((item) => item.profile.id === userId)
  if (!account) {
    // 令牌指向的账号不存在（如刷新后注册账号丢失）→ 与契约一致按令牌失效引导重登
    sessionMissing()
  }
  return account
}
