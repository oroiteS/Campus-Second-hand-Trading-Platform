// 业务类型入口：仅 re-export 契约生成类型（src/api/types.ts），禁止手写契约结构
import type { components } from '../api/types'

export type { components, paths, operations } from '../api/types'

export type HealthData = components['schemas']['HealthData']
export type ServiceHealth = components['schemas']['ServiceHealth']
export type EmbeddingHealth = components['schemas']['EmbeddingHealth']
export type UserSummary = components['schemas']['UserSummary']
export type Role = components['schemas']['Role']
export type AuthStatus = components['schemas']['AuthStatus']
