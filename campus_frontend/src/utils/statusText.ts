import type {
  AuthStatus,
  EmbeddingHealth,
  ProductCondition,
  ProductStatus,
  Role,
} from '../types'

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

/** 成色 5 档（契约 ProductCondition description 中文文案） */
export const CONDITION_TEXT: Record<ProductCondition, string> = {
  brand_new: '全新',
  as_new: '99 新',
  excellent: '九成新',
  good: '八成新',
  fair: '七成新及以下',
}

/** 商品状态（契约 ProductStatus；deleted 仅内部态，界面不展示已删条目） */
export const PRODUCT_STATUS_TEXT: Record<ProductStatus, string> = {
  on_sale: '在售',
  trading: '交易中',
  sold: '已售',
  off_sale: '已下架',
  deleted: '已删除',
}
