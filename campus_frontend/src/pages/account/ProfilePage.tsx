import { Button, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { Navigate } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useAuthStore } from '../../stores/authStore'
import { AUTH_STATUS_TEXT, ROLE_TEXT } from '../../utils/statusText'
import './account.css'

/** 个人中心（批次 0 占位）：展示 authStore 中的用户概要（契约 UserSummary 结构） */
export function ProfilePage() {
  const user = useAuthStore((s) => s.user)
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const navigate = useNavigate()

  // 页面入口守卫（与路由层 RequireAuth 双层拦截）
  if (!user) {
    return <Navigate to="/login" replace />
  }

  function handleLogout() {
    clearAuth()
    navigate('/login', { replace: true })
  }

  return (
    <div className="page-container">
      <PageHeader title="个人中心" description="资料编辑与头像上传将于批次 1 上线" />
      <dl className="profile-list">
        <div className="profile-list__item">
          <dt>用户 ID</dt>
          <dd>{user.id}</dd>
        </div>
        <div className="profile-list__item">
          <dt>昵称</dt>
          <dd>{user.nickname}</dd>
        </div>
        <div className="profile-list__item">
          <dt>展示名</dt>
          <dd>{user.display_name}</dd>
        </div>
        <div className="profile-list__item">
          <dt>角色</dt>
          <dd>
            <Tag>{ROLE_TEXT[user.role]}</Tag>
          </dd>
        </div>
        <div className="profile-list__item">
          <dt>认证状态</dt>
          <dd>
            <Tag>{AUTH_STATUS_TEXT[user.auth_status]}</Tag>
          </dd>
        </div>
        <div className="profile-list__item">
          <dt>信誉分</dt>
          <dd>{user.credit_score == null ? '暂无' : user.credit_score}</dd>
        </div>
      </dl>
      <Button danger onClick={handleLogout}>
        退出登录
      </Button>
    </div>
  )
}
