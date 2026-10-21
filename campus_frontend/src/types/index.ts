// 业务类型入口：仅 re-export 契约生成类型（src/api/types.ts），禁止手写契约结构
import type { components } from '../api/types'

export type { components, paths, operations } from '../api/types'

// ---- 系统（b0） ----
export type HealthData = components['schemas']['HealthData']
export type ServiceHealth = components['schemas']['ServiceHealth']
export type EmbeddingHealth = components['schemas']['EmbeddingHealth']

// ---- 用户域数据（b1 · 契约 0.2.0） ----
export type UserSummary = components['schemas']['UserSummary']
export type UserProfile = components['schemas']['UserProfile']
export type LoginData = components['schemas']['LoginData']
export type AuthApplication = components['schemas']['AuthApplication']
export type SchoolWithCampuses = components['schemas']['SchoolWithCampuses']
export type ImageRef = components['schemas']['ImageRef']
export type SchoolRef = components['schemas']['SchoolRef']
export type CampusRef = components['schemas']['CampusRef']

// ---- 用户域请求体（b1 · 契约 0.2.0） ----
export type RegisterInput = components['schemas']['RegisterInput']
export type LoginInput = components['schemas']['LoginInput']
export type PasswordResetInput = components['schemas']['PasswordResetInput']
export type ProfileUpdateInput = components['schemas']['ProfileUpdateInput']
export type PasswordChangeInput = components['schemas']['PasswordChangeInput']

// ---- 业务枚举 ----
export type Role = components['schemas']['Role']
export type AuthStatus = components['schemas']['AuthStatus']
export type UserAccountStatus = components['schemas']['UserAccountStatus']
