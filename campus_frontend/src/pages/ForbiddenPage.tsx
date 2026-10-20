import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'

/** 403：已登录但角色不足（如学生访问 /admin） */
export function ForbiddenPage() {
  const navigate = useNavigate()
  return (
    <div className="page-container">
      <Result
        status="403"
        title="403"
        subTitle="当前账号无权访问该页面"
        extra={
          <Button type="primary" onClick={() => navigate('/', { replace: true })}>
            返回首页
          </Button>
        }
      />
    </div>
  )
}
