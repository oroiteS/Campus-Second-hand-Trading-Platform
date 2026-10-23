import type {
  LoginData,
  LoginInput,
  LogoutData,
  PasswordResetInput,
  RegisterInput,
  UserProfile,
} from '../../types'
import { delay } from '../../utils/delay'
import {
  validateEmail,
  validateNicknameOptional,
  validatePassword,
  validateStudentNo,
  validateUsername,
} from '../../utils/validators'
import { ApiError } from '../http'
import {
  MOCK_ACCOUNTS,
  cloneProfile,
  mockClearSession,
  mockSetSession,
  nowIso,
  type MockAccount,
} from './users'

/**
 * mock 账号仓库：覆盖任务卡要求的登录三态 + 驳回演示态——
 * - student01 未认证学生（unverified）
 * - student02 已认证学生（approved，含学校/校区/头像/手机号合法样例）
 * - student03 被驳回学生（rejected，认证页演示驳回原因与重提）
 * - admin01 管理员（role = admin）
 * 全部初始密码 Pass1234；mock 明文仅内存演示，真实后端为 bcrypt（NFR-05）。
 */
const INITIAL_ACCOUNTS: MockAccount[] = [
  {
    password: 'Pass1234',
    profile: {
      id: 1001,
      username: 'student01',
      student_no: '2024010101',
      email: 'zhangsan01@example.edu.cn',
      nickname: '小张',
      display_name: '小张',
      phone: null,
      avatar: null,
      school: null,
      campus: null,
      role: 'student',
      auth_status: 'unverified',
      status: 'active',
      credit_score: null,
      created_at: '2026-09-01T09:00:00+08:00',
    },
  },
  {
    password: 'Pass1234',
    profile: {
      id: 1002,
      username: 'student02',
      student_no: '2024010102',
      email: 'xiaoming@example.edu.cn',
      nickname: '小明',
      display_name: '小明-示例大学(东校区)',
      phone: '13812345678',
      avatar: { id: 42, url: '/api/images/42' },
      school: { id: 1, name: '示例大学', multi_campus: true },
      campus: { id: 1, school_id: 1, name: '东校区' },
      role: 'student',
      auth_status: 'approved',
      status: 'active',
      credit_score: null,
      created_at: '2026-09-01T09:30:00+08:00',
    },
  },
  {
    password: 'Pass1234',
    profile: {
      id: 1003,
      username: 'student03',
      student_no: '2024010103',
      email: 'xiaohua@example.edu.cn',
      nickname: '小华',
      display_name: '小华',
      phone: null,
      avatar: null,
      school: null,
      campus: null,
      role: 'student',
      auth_status: 'rejected',
      status: 'active',
      credit_score: null,
      created_at: '2026-09-01T10:00:00+08:00',
    },
  },
  {
    password: 'Pass1234',
    profile: {
      id: 9001,
      username: 'admin01',
      student_no: '9001001',
      email: 'admin@example.edu.cn',
      nickname: '管理员',
      display_name: '管理员',
      phone: null,
      avatar: null,
      school: null,
      campus: null,
      role: 'admin',
      auth_status: 'approved',
      status: 'active',
      credit_score: null,
      created_at: '2026-09-01T08:00:00+08:00',
    },
  },
]

for (const account of INITIAL_ACCOUNTS) {
  MOCK_ACCOUNTS.push(account)
}

let nextUserIdSeed = 2000

function nextUserId(): number {
  nextUserIdSeed += 1
  return nextUserIdSeed
}

/** 连续登录失败计数（对应契约 rate:login:{ip}；登录成功清零） */
let loginFailCount = 0

/** 锁定截止时间戳（毫秒）：达到失败上限时记录，600 秒后自动解锁（对齐真实 Redis TTL） */
let loginLockedUntil: number | null = null

const LOGIN_FAIL_LIMIT = 5

const LOGIN_LOCK_MS = 600_000

/** 记一次登录失败；达到上限即锁定 600 秒 */
function registerLoginFail(): void {
  loginFailCount += 1
  if (loginFailCount >= LOGIN_FAIL_LIMIT) {
    loginLockedUntil = Date.now() + LOGIN_LOCK_MS
  }
}

/** POST /api/auth/login：三种账号登录、2005、2006、1006（连续 5 次失败后限流，600 秒自动解锁） */
export function mockLogin(body: LoginInput): Promise<LoginData> {
  return delay(400).then(() => {
    if (loginFailCount >= LOGIN_FAIL_LIMIT) {
      if (loginLockedUntil != null && Date.now() >= loginLockedUntil) {
        // 锁定期已过：自动解锁并重新计数（对齐 Redis TTL 过期语义）
        loginFailCount = 0
        loginLockedUntil = null
      } else {
        throw new ApiError(1006, '登录失败次数过多，请 10 分钟后重试', null)
      }
    }
    const found = MOCK_ACCOUNTS.find(
      (account) =>
        account.profile.username === body.account ||
        account.profile.student_no === body.account,
    )
    if (!found || found.password !== body.password) {
      registerLoginFail()
      throw new ApiError(2005, '用户名或密码错误', null)
    }
    if (found.profile.status === 'banned') {
      registerLoginFail()
      throw new ApiError(2006, '账号已被封禁', null)
    }
    loginFailCount = 0
    const profile = cloneProfile(found.profile)
    mockSetSession(profile)
    return {
      access_token: `mock-token-${found.profile.id}`,
      token_type: 'Bearer',
      expires_in: 86_400,
      user: profile,
    }
  })
}

/** POST /api/auth/register：9001 字段级复验（与 validators 同源）→ 2001/2002 → 建号（不签发令牌） */
export function mockRegister(body: RegisterInput): Promise<UserProfile> {
  return delay(500).then(() => {
    const fields: Record<string, string> = {}
    const usernameError = validateUsername(body.username)
    if (usernameError) fields.username = usernameError
    const passwordError = validatePassword(body.password)
    if (passwordError) fields.password = passwordError
    const emailError = validateEmail(body.email)
    if (emailError) fields.email = emailError
    const studentNoError = validateStudentNo(body.student_no)
    if (studentNoError) fields.student_no = studentNoError
    const nicknameError = validateNicknameOptional(body.nickname ?? '')
    if (nicknameError) fields.nickname = nicknameError
    if (Object.keys(fields).length > 0) {
      throw new ApiError(9001, '参数校验失败', { fields })
    }
    if (MOCK_ACCOUNTS.some((account) => account.profile.username === body.username)) {
      throw new ApiError(2001, '用户名已存在', null)
    }
    if (MOCK_ACCOUNTS.some((account) => account.profile.student_no === body.student_no)) {
      throw new ApiError(2002, '学号已被注册', null)
    }
    const nickname = body.nickname && body.nickname !== '' ? body.nickname : body.username
    const profile: UserProfile = {
      id: nextUserId(),
      username: body.username,
      student_no: body.student_no,
      email: body.email,
      nickname,
      display_name: nickname, // 未认证展示名 = 昵称（FR-USR-10）
      phone: null,
      avatar: null,
      school: null,
      campus: null,
      role: 'student',
      auth_status: 'unverified',
      status: 'active',
      credit_score: null,
      created_at: nowIso(),
    }
    MOCK_ACCOUNTS.push({ profile, password: body.password })
    return cloneProfile(profile)
  })
}

/**
 * POST /api/auth/logout：登出同时清除 mock 内存会话（与 authStore 清令牌一致）。
 * mock 走契约正常路径（data = {}）；Redis 故障降级（degraded/degraded_reason）
 * 由真实后端触发，消费端（ProfilePage）已按契约字段做用户可见提示。
 */
export function mockLogout(): Promise<LogoutData> {
  return delay(200).then(() => {
    mockClearSession()
    return {}
  })
}

/**
 * POST /api/auth/password/reset：9001 复验 → 2004（用户名不存在与凭证不匹配
 * 一律同码，不泄露存在性，防探测）→ 更新 mock 账号密码。
 */
export function mockResetPassword(body: PasswordResetInput): Promise<void> {
  return delay(450).then(() => {
    const fields: Record<string, string> = {}
    if (!body.username.trim()) {
      fields.username = '请输入用户名'
    }
    const newPasswordError = validatePassword(body.new_password)
    if (newPasswordError) fields.new_password = newPasswordError
    if (!body.reset_value.trim()) {
      fields.reset_value = body.reset_channel === 'email' ? '请输入注册邮箱' : '请输入注册学号'
    } else if (body.reset_channel === 'email') {
      const emailError = validateEmail(body.reset_value)
      if (emailError) fields.reset_value = emailError
    }
    if (Object.keys(fields).length > 0) {
      throw new ApiError(9001, '参数校验失败', { fields })
    }
    const found = MOCK_ACCOUNTS.find((account) => account.profile.username === body.username)
    const credentialMatched =
      found != null &&
      (body.reset_channel === 'student_no'
        ? found.profile.student_no === body.reset_value
        : found.profile.email === body.reset_value)
    if (!found || !credentialMatched) {
      throw new ApiError(2004, '重置凭证不匹配', null)
    }
    found.password = body.new_password
  })
}
