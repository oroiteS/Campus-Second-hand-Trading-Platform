import { ApiError } from '../api/http'

/** 是否为令牌类错误（1001 缺失/无效、1002 过期、1003 注销）：页面据此避免重复引导（http 层已统一跳登录） */
export function isTokenInvalidError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === 1001 || error.code === 1002 || error.code === 1003)
  )
}

function isStringRecord(value: unknown): value is Record<string, string> {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  return Object.values(value).every((item) => typeof item === 'string')
}

function hasFields(value: unknown): value is { fields: unknown } {
  return typeof value === 'object' && value !== null && 'fields' in value
}

/**
 * 从 9001 错误中安全提取字段级错误（字段名 → 用户可见文案）。
 * 非 9001 或 data.fields 结构不符时返回 null，由调用方走表单级反馈。
 */
export function extractFieldErrors(error: unknown): Record<string, string> | null {
  if (!(error instanceof ApiError) || error.code !== 9001) {
    return null
  }
  if (!hasFields(error.data)) {
    return null
  }
  const fields = error.data.fields
  return isStringRecord(fields) ? fields : null
}

/** 从 ApiError 提取用户可见文案；非 ApiError 返回兜底文案 */
export function errorMessage(error: unknown, fallback = '请求失败，请稍后重试'): string {
  if (error instanceof ApiError && error.message) {
    return error.message
  }
  return fallback
}
