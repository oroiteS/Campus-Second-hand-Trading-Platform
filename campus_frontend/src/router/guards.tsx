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

/**
 * 需通过校园认证（b2 商品域浏览面：首页推荐 / 列表 / 详情 / 搜索）：
 * 游客 → 登录页；未认证用户 → 认证页（AC-02 最硬准入线，商品域一律不可见）。
 * 管理员按契约可跨校区浏览（scope_all），放行。
 */
export function RequireVerified() {
  const phase = useAuthPhase()
  const location = useLocation()
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}

/**
 * 需认证学生（发布 / 编辑 / 我的商品 / 我的收藏——管理员无交易能力）：
 * 游客 → 登录页；未认证 → 认证页；管理员 → 403。
 */
export function RequireStudent() {
  const phase = useAuthPhase()
  const location = useLocation()
  if (phase === 'guest') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (phase === 'unverified') {
    return <Navigate to="/certification" replace state={{ from: location.pathname }} />
  }
  if (phase === 'admin') {
    return <ForbiddenPage />
  }
  return <Outlet />
}
