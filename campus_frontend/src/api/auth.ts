import type {
  LoginData,
  LoginInput,
  LogoutData,
  PasswordResetInput,
  RegisterInput,
  UserProfile,
} from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockLogin, mockLogout, mockRegister, mockResetPassword } from './mock/auth'

/** POST /api/auth/register：注册（公开；成功不签发令牌，需再登录） */
export function register(body: RegisterInput): Promise<UserProfile> {
  if (USE_MOCK) {
    return mockRegister(body)
  }
  return http.post<UserProfile>('/auth/register', body).then((res) => res.data)
}

/** POST /api/auth/login：登录（公开；account 先按用户名精确匹配，未命中按学号） */
export function login(body: LoginInput): Promise<LoginData> {
  if (USE_MOCK) {
    return mockLogin(body)
  }
  return http.post<LoginData>('/auth/login', body).then((res) => res.data)
}

/** POST /api/auth/logout：登出（需登录；令牌 jti 入 Redis 黑名单；降级时 data 附 degraded 字段） */
export function logout(): Promise<LogoutData> {
  if (USE_MOCK) {
    return mockLogout()
  }
  return http.post<LogoutData>('/auth/logout').then((res) => res.data)
}

/** POST /api/auth/password/reset：重置密码（公开；2004 不泄露用户名存在性） */
export function resetPassword(body: PasswordResetInput): Promise<void> {
  if (USE_MOCK) {
    return mockResetPassword(body)
  }
  return http.post<void>('/auth/password/reset', body).then(() => undefined)
}
