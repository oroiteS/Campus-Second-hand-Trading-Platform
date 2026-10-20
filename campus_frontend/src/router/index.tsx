import { createBrowserRouter } from 'react-router-dom'
import { AdminLayout } from '../layouts/AdminLayout'
import { UserLayout } from '../layouts/UserLayout'
import { GuestOnly, RequireAdmin, RequireAuth } from './guards'
import {
  AdminDashboardPage,
  CertificationPage,
  ForgotPasswordPage,
  HomePage,
  LoginPage,
  NotFoundPage,
  ProfilePage,
  RegisterPage,
} from './lazyPages'

/**
 * 路由表（批次 0 骨架）：
 * - 公开：/（首页健康面板）、游客专属 auth 三页（GuestOnly）
 * - 需登录（RequireAuth）：/certification、/profile
 * - 需管理员（RequireAdmin）：/admin
 * 页面入口另有二次守卫（见各页面），路由 + 页面双层拦截。
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <UserLayout />,
    children: [
      { index: true, element: <HomePage /> },
      {
        element: <GuestOnly />,
        children: [
          { path: 'login', element: <LoginPage /> },
          { path: 'register', element: <RegisterPage /> },
          { path: 'forgot-password', element: <ForgotPasswordPage /> },
        ],
      },
      {
        element: <RequireAuth />,
        children: [
          { path: 'certification', element: <CertificationPage /> },
          { path: 'profile', element: <ProfilePage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    path: '/admin',
    element: <RequireAdmin />,
    children: [
      {
        element: <AdminLayout />,
        children: [{ index: true, element: <AdminDashboardPage /> }],
      },
    ],
  },
])
