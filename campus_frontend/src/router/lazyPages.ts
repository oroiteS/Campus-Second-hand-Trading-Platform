import { lazy } from 'react'

// 路由级代码分割（React.lazy，Suspense fallback 见各布局）
// 本文件只导出 lazy 组件，保持 fast refresh 合规
export const HomePage = lazy(() =>
  import('../pages/home/HomePage').then((m) => ({ default: m.HomePage })),
)
export const LoginPage = lazy(() =>
  import('../pages/auth/LoginPage').then((m) => ({ default: m.LoginPage })),
)
export const RegisterPage = lazy(() =>
  import('../pages/auth/RegisterPage').then((m) => ({ default: m.RegisterPage })),
)
export const ForgotPasswordPage = lazy(() =>
  import('../pages/auth/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage })),
)
export const CertificationPage = lazy(() =>
  import('../pages/account/CertificationPage').then((m) => ({ default: m.CertificationPage })),
)
export const ProfilePage = lazy(() =>
  import('../pages/account/ProfilePage').then((m) => ({ default: m.ProfilePage })),
)
export const AdminDashboardPage = lazy(() =>
  import('../pages/admin/AdminDashboardPage').then((m) => ({ default: m.AdminDashboardPage })),
)
export const ProductListPage = lazy(() =>
  import('../pages/product/ProductListPage').then((m) => ({ default: m.ProductListPage })),
)
export const ProductDetailPage = lazy(() =>
  import('../pages/product/ProductDetailPage').then((m) => ({ default: m.ProductDetailPage })),
)
export const ProductPublishPage = lazy(() =>
  import('../pages/product/ProductPublishPage').then((m) => ({ default: m.ProductPublishPage })),
)
export const MyProductsPage = lazy(() =>
  import('../pages/product/MyProductsPage').then((m) => ({ default: m.MyProductsPage })),
)
export const MyFavoritesPage = lazy(() =>
  import('../pages/product/MyFavoritesPage').then((m) => ({ default: m.MyFavoritesPage })),
)
export const SearchPage = lazy(() =>
  import('../pages/product/SearchPage').then((m) => ({ default: m.SearchPage })),
)
export const NotFoundPage = lazy(() =>
  import('../pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })),
)
