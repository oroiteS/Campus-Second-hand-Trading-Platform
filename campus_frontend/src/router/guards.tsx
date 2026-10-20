import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { ForbiddenPage } from '../pages/ForbiddenPage'
import { useAuthPhase } from '../stores/authStore'

/** 已登录用户不可见（注册 / 登录 / 找回密码）：重定向首页 */
export function GuestOnly() {
  const phase = useAuthPhase()
  if (phase !== 'guest') {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}

/** 需登录（个人中心 / 校园认证）：游客 → 登录页，记录来源路径 */
export function RequireAuth() {
  const phase = useAuthPhase()
  const location = useLocation()
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}

/** 需管理员（/admin）：游客 → 登录页；已登录非管理员 → 403 */
export function RequireAdmin() {
  const phase = useAuthPhase()
  const location = useLocation()
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase !== 'admin') {
    return <ForbiddenPage />
  }
  return <Outlet />
}
