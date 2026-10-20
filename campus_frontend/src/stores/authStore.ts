import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { DEMO_USERS } from '../api/mock/system'
import type { UserSummary } from '../types'

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
  user: UserSummary | null
  setAuth: (token: string, user: UserSummary) => void
  clearAuth: () => void
  /** 开发演示：一键切换四态，验证路由守卫（批次 0 无登录接口） */
  setDemoPhase: (phase: AuthPhase) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      clearAuth: () => set({ token: null, user: null }),
      setDemoPhase: (phase) => {
        if (phase === 'guest') {
          set({ token: null, user: null })
          return
        }
        set({ token: `demo-token-${phase}`, user: DEMO_USERS[phase] })
      },
    }),
    { name: 'campus-auth' },
  ),
)

function phaseOf(token: string | null, user: UserSummary | null): AuthPhase {
  if (!token || !user) return 'guest'
  if (user.role === 'admin') return 'admin'
  return user.auth_status === 'approved' ? 'student' : 'unverified'
}

/** 派生四态；认证状态与角色以用户信息为准，不本地推测 */
export function useAuthPhase(): AuthPhase {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  return phaseOf(token, user)
}
