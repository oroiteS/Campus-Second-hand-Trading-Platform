import { Suspense } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { RouteLoading } from '../components/RouteLoading'
import { useAuthPhase, useAuthStore } from '../stores/authStore'
import './UserLayout.css'

/**
 * 前台布局：语义 landmark（header / main / footer）+ skip link。
 * 主内容锚点 <main id="main-content">，供跳过导航与 hash 定位。
 * 导航按四态收敛：登录后可见商品浏览入口；学生独占发布/我的商品/收藏。
 */
export function UserLayout() {
  const phase = useAuthPhase()
  const user = useAuthStore((s) => s.user)
  const isLoggedIn = phase !== 'guest'
  const isStudent = phase === 'student'
  const isAdmin = phase === 'admin'

  return (
    <div className="user-layout">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>

      <header className="user-layout__header">
        <div className="user-layout__header-inner">
          <Link to="/" className="user-layout__brand">
            <img src="/favicon.svg" alt="" width="28" height="28" />
            <span>校园二手交易平台</span>
          </Link>

          <nav className="user-layout__nav" aria-label="主导航">
            <ul>
              <li>
                <NavLink to="/" end>
                  首页
                </NavLink>
              </li>
              {isLoggedIn && (
                <li>
                  <NavLink to="/products">商品列表</NavLink>
                </li>
              )}
              {isLoggedIn && (
                <li>
                  <NavLink to="/search">搜索</NavLink>
                </li>
              )}
              {isStudent && (
                <li>
                  <NavLink to="/publish">发布</NavLink>
                </li>
              )}
              {isStudent && (
                <li>
                  <NavLink to="/my/products">我的商品</NavLink>
                </li>
              )}
              {isStudent && (
                <li>
                  <NavLink to="/my/favorites">收藏</NavLink>
                </li>
              )}
              {isLoggedIn && !isStudent && (
                <li>
                  <NavLink to="/certification">校园认证</NavLink>
                </li>
              )}
              {isLoggedIn && (
                <li>
                  <NavLink to="/profile">个人中心</NavLink>
                </li>
              )}
              {isAdmin && (
                <li>
                  <NavLink to="/admin">管理后台</NavLink>
                </li>
              )}
            </ul>
          </nav>

          <div className="user-layout__actions">
            {isLoggedIn ? (
              <span className="user-layout__user">{user?.nickname}</span>
            ) : (
              <Link to="/login" className="user-layout__login">
                登录
              </Link>
            )}
          </div>
        </div>
      </header>

      <main id="main-content" className="user-layout__main" tabIndex={-1}>
        <Suspense fallback={<RouteLoading />}>
          <Outlet />
        </Suspense>
      </main>

      <footer className="user-layout__footer">
        <p>校园二手交易平台 · 本校学生二手好物集市</p>
      </footer>
    </div>
  )
}
