import { Alert, Button, Tag } from 'antd'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Empty } from 'antd'
import { PageHeader } from '../../components/PageHeader'
import { useAuthStore } from '../../stores/authStore'
import { AUTH_STATUS_TEXT } from '../../utils/statusText'
import type { AuthStatus } from '../../types'
import './account.css'

const STATUS_TAG_COLOR: Record<AuthStatus, 'default' | 'processing' | 'success' | 'error'> = {
  unverified: 'default',
  pending: 'processing',
  approved: 'success',
  rejected: 'error',
}

/**
 * 校园认证状态页（批次 0 占位）：按 auth_status 展示四类状态，
 * 未认证为空态（含批次 1 上线的占位提交入口）。
 */
export function CertificationPage() {
  const user = useAuthStore((s) => s.user)
  const [notice, setNotice] = useState<string | null>(null)

  // 页面入口守卫（与路由层 RequireAuth 双层拦截）
  if (!user) {
    return <Navigate to="/login" replace />
  }

  const status: AuthStatus = user.auth_status

  return (
    <div className="page-container">
      <PageHeader
        title="校园认证"
        description="认证通过后才能访问商品交易功能（平台最硬准入线）"
      />

      {notice && (
        <p className="account-notice" role="alert">
          {notice}
        </p>
      )}

      {status === 'unverified' && (
        <section aria-labelledby="cert-empty-heading" className="account-panel">
          <Empty description="尚未提交校园认证">
            <div className="account-panel__intro">
              <h2 id="cert-empty-heading" className="visually-hidden">
                未提交认证
              </h2>
              <p>提交学生证照片与基本信息，管理员审核通过后即可解锁商品发布与交易。</p>
              <Button
                type="primary"
                onClick={() => setNotice('认证提交功能将于批次 1 开放，敬请期待。')}
              >
                提交认证
              </Button>
            </div>
          </Empty>
        </section>
      )}

      {status === 'pending' && (
        <Alert
          type="info"
          showIcon
          message="认证审核中"
          description="管理员正在审核你的认证材料，审核结果将通过站内通知告知。"
        />
      )}

      {status === 'approved' && (
        <Alert
          type="success"
          showIcon
          message="已通过校园认证"
          description="你可以使用商品发布、浏览与交易等全部学生功能。"
        />
      )}

      {status === 'rejected' && (
        <Alert
          type="error"
          showIcon
          role="alert"
          message="认证被驳回"
          description="驳回原因：材料不清晰（演示文案，真实原因随批次 1 接口返回）。可修改材料后重新提交。"
        />
      )}

      <p className="account-meta">
        当前状态：<Tag color={STATUS_TAG_COLOR[status]}>{AUTH_STATUS_TEXT[status]}</Tag>
      </p>
    </div>
  )
}
