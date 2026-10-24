/**
 * 路由 state 安全读取（react-router location.state 为 unknown）。
 * 注册成功回填账号、登录后回跳来源路径等场景统一走这里。
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 读取字符串字段；缺失或类型不符返回 undefined */
export function readStateString(state: unknown, key: string): string | undefined {
  if (!isRecord(state) || !(key in state)) {
    return undefined
  }
  const value = state[key]
  return typeof value === 'string' ? value : undefined
}

/**
 * 是否为站内绝对路径（可安全用于导航 / 回跳）。
 * 拒绝三类注入形态：
 * - 非 `/` 开头（相对路径、绝对 URL、空值）；
 * - 协议相对路径 `//evil.com`（浏览器按当前协议跨域跳转）；
 * - 含反斜杠的 `/\\evil.com`（部分浏览器会归一化为协议相对路径）。
 */
export function isInternalPath(value: string | null | undefined): value is string {
  if (value == null || !value.startsWith('/')) {
    return false
  }
  if (value.startsWith('//') || value.includes('\\')) {
    return false
  }
  return true
}

/** 读取站内路径字段（须为站内路径，防外链注入）；不符返回 undefined */
export function readStatePath(state: unknown, key: string): string | undefined {
  const value = readStateString(state, key)
  return isInternalPath(value) ? value : undefined
}
