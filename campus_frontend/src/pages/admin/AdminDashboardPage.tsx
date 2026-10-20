import { Card, Empty } from 'antd'
import { Navigate } from 'react-router-dom'
import { PageHeader } from '../../components/PageHeader'
import { useAuthStore } from '../../stores/authStore'

/** 管理后台概览（批次 0 占位）：审核队列 / 用户 / 商品 / 统计等批次 5 上线 */
export function AdminDashboardPage() {
  const user = useAuthStore((s) => s.user)

  // 页面入口守卫（与路由层 RequireAdmin 双层拦截）
  if (!user || user.role !== 'admin') {
    return <Navigate to="/login" replace />
  }

  return (
    <div>
      <PageHeader
        title="管理后台概览"
        description={`欢迎，${user.display_name}（管理员不具备发布与交易能力）`}
      />
      <Card size="small">
        <Empty description="认证审核、用户与商品处置、统计报表等管理功能将于批次 5 上线" />
      </Card>
    </div>
  )
}
