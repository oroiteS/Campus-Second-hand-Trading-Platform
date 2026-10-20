import { Suspense } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { AuthDemoSwitcher } from '../components/AuthDemoSwitcher'
import { RouteLoading } from '../components/RouteLoading'
import './AdminLayout.css'

/**
 * 管理端布局：侧边导航 + 主内容。
 * 管理员不出现发布 / 下单入口（权限矩阵红线）。
 */
export function AdminLayout() {
  return (
    <div className="admin-layout">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>

      <div className="admin-layout__frame">
        <aside className="admin-layout__sidebar">
          <div className="admin-layout__brand">
            <img src="/favicon.svg" alt="" width="28" height="28" />
            <span>管理后台</span>
          </div>
          <nav className="admin-layout__nav" aria-label="管理端导航">
            <ul>
              <li>
                <NavLink to="/admin" end>
                  概览
                </NavLink>
              </li>
            </ul>
          </nav>
          <div className="admin-layout__sidebar-footer">
            <Link to="/">返回前台</Link>
          </div>
        </aside>

        <div className="admin-layout__content">
          <header className="admin-layout__header">
            <span className="admin-layout__scope">校园二手交易平台 · 管理端</span>
            <AuthDemoSwitcher />
          </header>
          <main id="main-content" className="admin-layout__main" tabIndex={-1}>
            <Suspense fallback={<RouteLoading />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  )
}
