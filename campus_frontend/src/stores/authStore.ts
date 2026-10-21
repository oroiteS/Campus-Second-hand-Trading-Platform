import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { UserProfile } from '../types'

/**
 * 路由四态（权限矩阵界面落点）：
 * - guest       游客：未持有令牌
 * - unverified  未认证用户：已登录且 auth_status != approved（学生）
 * - student     认证学生：已登录且 approved（学生）
 * - admin       管理员：role = admin
 */
export type AuthPhase = 'guest' | 'unverified' | 'student' | 'admin'

interface AuthState {
  token: string | null
  user: UserProfile | null
  /** 登录成功：写入 access_token 与用户完整资料（LoginData.user） */
  setAuth: (token: string, user: UserProfile) => void
  /** 登录后局部刷新资料（改资料/头像/认证状态流转），令牌不变 */
  setUser: (user: UserProfile) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      clearAuth: () => set({ token: null, user: null }),
    }),
    { name: 'campus-auth' },
  ),
)

function phaseOf(token: string | null, user: UserProfile | null): AuthPhase {
  if (!token || !user) return 'guest'
  if (user.role === 'admin') return 'admin'
  return user.auth_status === 'approved' ? 'student' : 'unverified'
}

/** 派生四态；认证状态与角色以接口返回的用户信息为准，不本地推测 */
export function useAuthPhase(): AuthPhase {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  return phaseOf(token, user)
}
