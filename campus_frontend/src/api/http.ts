import axios, { AxiosError, type AxiosResponse } from 'axios'
import { useAuthStore } from '../stores/authStore'
import { API_BASE } from './config'
import type { components } from './types'

type SuccessEnvelope = components['schemas']['SuccessEnvelope']
type ErrorEnvelope = components['schemas']['ErrorEnvelope']
type Envelope = SuccessEnvelope | ErrorEnvelope

/** 业务错误对象：保留契约 envelope 的 code / message / data，供页面做用户可见反馈 */
export class ApiError extends Error {
  readonly code: number
  readonly data: unknown

  constructor(code: number, message: string, data: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
  }
}

/** 运行时识别契约统一响应体 { code, message, data } */
function isEnvelope(value: unknown): value is Envelope {
  if (typeof value !== 'object' || value === null) return false
  if (!('code' in value) || !('message' in value)) return false
  return typeof value.code === 'number' && typeof value.message === 'string'
}

/** 令牌类错误码（1001 缺失/无效、1002 过期、1003 注销）→ 清除本地令牌并引导登录 */
function isTokenInvalidCode(code: number): boolean {
  return code === 1001 || code === 1002 || code === 1003
}

/** 游客页路径：令牌失效引导时避免登录/注册/找回密码页循环跳转 */
const GUEST_PATHS = ['/login', '/register', '/forgot-password']

function isGuestPath(pathname: string): boolean {
  return GUEST_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))
}

/**
 * 令牌失效统一引导：清令牌；当前路由非游客页时整页跳转登录（数据全部失效，不用路由内导航）。
 * http 响应拦截器与 mock 会话缺失路径共用，保证契约「令牌失效 → 清令牌并引导重新登录」
 * 在真实请求与 mock 两条链路上一致成立。
 */
export function handleTokenInvalid(): void {
  useAuthStore.getState().clearAuth()
  if (!isGuestPath(window.location.pathname)) {
    window.location.assign('/login')
  }
}

/** 需校园认证的页面（1004 引导目标；自身不再触发引导，防循环跳转） */
const CERTIFICATION_PATH = '/certification'

/**
 * 1004（未通过校园认证）统一引导（b2）：当前路由为游客页或认证页本身时不跳转
 * （认证页自身不触发，任务卡铁律）；否则整页引导至 /certification 并携带 from
 * 回跳参数。与 401 引导共用「游客页不跳转」的防循环逻辑。
 * 页面内 RequireVerified 守卫为主拦截，本引导兜底「守卫放行后令牌态变化」的
 * 时序缝隙（http 拦截器与 mock 商品域准入共用）。
 */
export function handleCertificationRequired(): void {
  const pathname = window.location.pathname
  if (isGuestPath(pathname) || pathname === CERTIFICATION_PATH) {
    return
  }
  const from = `${pathname}${window.location.search}`
  window.location.assign(
    `${CERTIFICATION_PATH}?from=${encodeURIComponent(from)}`,
  )
}

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 10_000,
})

// 请求拦截：携带 Bearer 令牌
http.interceptors.request.use((config) => {
  const { token } = useAuthStore.getState()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：解 { code, message, data } envelope；code != 0 抛 ApiError
http.interceptors.response.use(
  (response: AxiosResponse) => {
    if (!isEnvelope(response.data)) {
      // 非 envelope 响应（如文件流）原样返回
      return response
    }
    const envelope = response.data
    if (envelope.code !== 0) {
      throw new ApiError(envelope.code, envelope.message, envelope.data ?? null)
    }
    response.data = envelope.data
    return response
  },
  (error: unknown) => {
    if (error instanceof AxiosError) {
      if (error.response) {
        // 契约约定：错误响应 HTTP 层为语义化状态码，body 仍为 envelope
        const body: unknown = error.response.data
        if (isEnvelope(body)) {
          if (isTokenInvalidCode(body.code)) {
            handleTokenInvalid()
          }
          // 1004（未通过校园认证）：非游客页/非认证页时统一引导认证页（防循环）
          if (body.code === 1004) {
            handleCertificationRequired()
          }
          return Promise.reject(new ApiError(body.code, body.message, body.data ?? null))
        }
        return Promise.reject(
          new ApiError(-1, `请求失败（HTTP ${error.response.status}）`, null),
        )
      }
      if (error.code === 'ECONNABORTED') {
        return Promise.reject(new ApiError(-1, '请求超时，请稍后重试', null))
      }
      return Promise.reject(new ApiError(-1, '网络异常，请检查网络后重试', null))
    }
    return Promise.reject(error)
  },
)
