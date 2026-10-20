import type { AuthStatus, EmbeddingHealth, Role } from '../types'

/**
 * 枚举值一律英文小写（契约值域），中文仅做展示映射，不得改写值本身。
 */
export const AUTH_STATUS_TEXT: Record<AuthStatus, string> = {
  unverified: '未认证',
  pending: '审核中',
  approved: '已通过',
  rejected: '已驳回',
}

export const ROLE_TEXT: Record<Role, string> = {
  student: '学生',
  admin: '管理员',
}

export const EMBEDDING_MODE_TEXT: Record<Exclude<EmbeddingHealth['mode'], null>, string> = {
  cloud: '云端模式',
  local: '本地兜底',
}
