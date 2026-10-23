/**
 * 表单字段预检唯一口径（docs/plan/01-用户域.md 与 docs/plan/02-商品域.md「3.0 字段校验对照表」）。
 *
 * - 全部表单（登录 / 注册 / 找回密码 / 资料编辑 / 改密 / 认证提交 / 商品发布编辑 / 列表筛选）
 *   的客户端预检一律引用本文件，不得在各页面另写规则；
 * - api/mock 复用同一批函数模拟后端 9001 复验，保证「双端同源」演示口径一致；
 * - 预检仅提升体验，不替代后端复验；后端校验失败统一 422 / 9001（data.fields），
 *   页面须将 fields 逐字段内联展示。
 *
 * 约定：校验函数返回 null 表示通过，否则返回用户可见的错误文案。
 */

/** 用户名：1–32 位，字母开头，仅字母/数字/下划线（注册后不可改） */
export const USERNAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,31}$/

/** 密码：8–64 位，须同时包含字母与数字 */
export const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/

/** 手机号：1 开头的 11 位纯数字（空串表示清除，另行放行） */
export const PHONE_PATTERN = /^1\d{10}$/

/** 邮箱：标准 email 形态（契约 format: email） */
export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateUsername(value: string): string | null {
  if (!value.trim()) {
    return '请输入用户名'
  }
  if (!USERNAME_PATTERN.test(value)) {
    return '用户名须为 1–32 位、字母开头，仅含字母/数字/下划线'
  }
  return null
}

export function validatePassword(value: string): string | null {
  if (!value) {
    return '请输入密码'
  }
  if (!PASSWORD_PATTERN.test(value)) {
    return '密码长度须为 8–64 位，且同时包含字母与数字'
  }
  return null
}

/** 手机号可空：空串 = 清除（契约语义），直接放行 */
export function validatePhoneOptional(value: string): string | null {
  if (value === '') {
    return null
  }
  if (!PHONE_PATTERN.test(value)) {
    return '手机号须为 1 开头的 11 位纯数字'
  }
  return null
}

export function validateEmail(value: string): string | null {
  if (!value.trim()) {
    return '请输入邮箱'
  }
  if (!EMAIL_PATTERN.test(value)) {
    return '邮箱格式不正确'
  }
  return null
}

/** 必填（用于纯文本必填项，如登录账号、找回用户名） */
export function validateRequired(value: string, label: string): string | null {
  if (!value.trim()) {
    return `请输入${label}`
  }
  return null
}

/** 长度 1–32 的通用校验（学号 / 昵称 / 真实姓名 / 账号等） */
export function validateLength(value: string, label: string, min: number, max: number): string | null {
  if (value.length < min) {
    return `${label}长度不得少于 ${min} 个字符`
  }
  if (value.length > max) {
    return `${label}长度不得超过 ${max} 个字符`
  }
  return null
}

/** 登录账号：用户名或学号，1–32 字符（登录时不校验字符构成） */
export function validateAccount(value: string): string | null {
  const required = validateRequired(value, '账号')
  if (required) {
    return required
  }
  return validateLength(value, '账号', 1, 32)
}

/** 学号：1–32 字符（不限定纯数字；注册后不可改） */
export function validateStudentNo(value: string): string | null {
  const required = validateRequired(value, '学号')
  if (required) {
    return required
  }
  return validateLength(value, '学号', 1, 32)
}

/** 昵称可选：缺省取用户名（注册）；空串放行，填写时 1–32 */
export function validateNicknameOptional(value: string): string | null {
  if (value === '') {
    return null
  }
  return validateLength(value, '昵称', 1, 32)
}

/** 真实姓名：1–32 字符（认证提交） */
export function validateRealName(value: string): string | null {
  const required = validateRequired(value, '真实姓名')
  if (required) {
    return required
  }
  return validateLength(value, '真实姓名', 1, 32)
}

/** 上传文件预检：仅 jpg/png/webp，≤ 5 MB（最终以接口校验为准） */
export const UPLOAD_MAX_MB = 5

const UPLOAD_ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export function validateUploadFile(file: File, label: string): string | null {
  if (!UPLOAD_ALLOWED_TYPES.includes(file.type)) {
    return `${label}仅支持 jpg / png / webp 格式`
  }
  if (file.size > UPLOAD_MAX_MB * 1024 * 1024) {
    return `${label}大小不得超过 ${UPLOAD_MAX_MB} MB`
  }
  return null
}

// ---- 商品域（b2 · docs/plan/02-商品域.md「3.0 字段校验对照表」） ----
// 三张商品表单（发布 / 编辑 / 筛选）共用本节，不得各写各的；
// api/mock 复用同批函数模拟后端 9001 复验（双端同源）。

/** 商品价格：`^\d{1,5}(\.\d{1,2})?$` 且数值 0.01–99999.99（original_price 同则可空） */
export const PRICE_PATTERN = /^\d{1,5}(\.\d{1,2})?$/

export const PRICE_MIN = 0.01

export const PRICE_MAX = 99999.99

/** 价格（必填）：0.01–99999.99 元，最多两位小数 */
export function validatePrice(value: string, label = '价格'): string | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return `请输入${label}`
  }
  if (!PRICE_PATTERN.test(trimmed)) {
    return `${label}须为最多两位小数的数字`
  }
  const num = Number(trimmed)
  if (num < PRICE_MIN || num > PRICE_MAX) {
    return `${label}须在 ${PRICE_MIN}–${PRICE_MAX} 元之间`
  }
  return null
}

/** 原价（可空）：填写时约束同 price */
export function validatePriceOptional(value: string, label = '原价'): string | null {
  if (value.trim() === '') {
    return null
  }
  return validatePrice(value, label)
}

/** 筛选价格边界（可空）：填写时须为不超过两位小数的非负数（0 允许作边界） */
export function validatePriceFilter(value: string, label: string): string | null {
  const trimmed = value.trim()
  if (trimmed === '') {
    return null
  }
  if (!PRICE_PATTERN.test(trimmed)) {
    return `${label}须为不超过两位小数的非负数字`
  }
  return null
}

/** 价格区间：min ≤ max（格式错误由 validatePriceFilter 字段级负责，此处只判次序） */
export function validatePriceRange(min: string, max: string): string | null {
  if (min.trim() === '' || max.trim() === '') {
    return null
  }
  if (!PRICE_PATTERN.test(min.trim()) || !PRICE_PATTERN.test(max.trim())) {
    return null
  }
  if (Number(min) > Number(max)) {
    return '价格下界不得大于价格上界'
  }
  return null
}

/** 商品标题：1–50 字符 */
export function validateTitle(value: string): string | null {
  if (!value.trim()) {
    return '请输入标题'
  }
  if (value.length > 50) {
    return '标题长度不得超过 50 个字符'
  }
  return null
}

/** 商品描述：1–2000 字符 */
export function validateDescription(value: string): string | null {
  if (!value.trim()) {
    return '请输入描述'
  }
  if (value.length > 2000) {
    return '描述长度不得超过 2000 个字符'
  }
  return null
}

/** 搜索词：1–100 字符（空白视为未填写） */
export function validateSearchQ(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return '请输入搜索词'
  }
  if (trimmed.length > 100) {
    return '搜索词长度不得超过 100 个字符'
  }
  return null
}

/** 列表关键词（可空）：0–100 字符，LIKE 标题匹配（契约 GET /api/products keyword） */
export function validateKeywordOptional(value: string): string | null {
  if (value.trim() === '') {
    return null
  }
  if (value.length > 100) {
    return '关键词长度不得超过 100 个字符'
  }
  return null
}
