import { Select } from 'antd'
import { useAuthPhase, useAuthStore, type AuthPhase } from '../stores/authStore'
import './AuthDemoSwitcher.css'

const PHASE_OPTIONS: { value: AuthPhase; label: string }[] = [
  { value: 'guest', label: '游客' },
  { value: 'unverified', label: '未认证学生' },
  { value: 'student', label: '认证学生' },
  { value: 'admin', label: '管理员' },
]

/**
 * 开发演示入口：一键切换路由四态，验证守卫拦截。
 * 批次 1 接入真实登录后移除。
 */
export function AuthDemoSwitcher() {
  const phase = useAuthPhase()
  const setDemoPhase = useAuthStore((s) => s.setDemoPhase)

  return (
    <div className="auth-demo-switcher">
      <span className="auth-demo-switcher__label">演示登录态</span>
      <Select
        aria-label="切换演示登录态（开发用）"
        value={phase}
        options={PHASE_OPTIONS}
        onChange={(value) => setDemoPhase(value)}
        popupMatchSelectWidth={false}
      />
    </div>
  )
}
