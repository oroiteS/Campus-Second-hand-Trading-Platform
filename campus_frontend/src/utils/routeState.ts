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

/** 读取站内路径字段（须以 / 开头，防外链注入）；不符返回 undefined */
export function readStatePath(state: unknown, key: string): string | undefined {
  const value = readStateString(state, key)
  return value && value.startsWith('/') ? value : undefined
}
