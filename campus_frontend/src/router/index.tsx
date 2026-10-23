import { createBrowserRouter } from 'react-router-dom'
import { AdminLayout } from '../layouts/AdminLayout'
import { UserLayout } from '../layouts/UserLayout'
import { GuestOnly, RequireAdmin, RequireAuth, RequireVerified } from './guards'
import {
  AdminDashboardPage,
  CertificationPage,
  ForgotPasswordPage,
  HomePage,
  LoginPage,
  NotFoundPage,
  ProductDetailPage,
  ProductListPage,
  ProfilePage,
  RegisterPage,
} from './lazyPages'

/**
 * 路由表：
 * - 游客专属 auth 三页（GuestOnly）；需登录（RequireAuth）：/certification、/profile
 * - 商品域浏览面（RequireVerified）：首页推荐（AC-02 准入线）
 * - 商品域学生面（RequireStudent，后续步骤增量接入）
 * - 需管理员（RequireAdmin）：/admin
 * 页面入口另有二次守卫（见各页面），路由 + 页面双层拦截。
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <UserLayout />,
    children: [
      {
        element: <RequireVerified />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'products', element: <ProductListPage /> },
          { path: 'products/:id', element: <ProductDetailPage /> },
        ],
      },
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
