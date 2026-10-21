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

/** 401 统一引导：清令牌；当前路由非游客页时整页跳转登录（数据全部失效，不用路由内导航） */
function handleTokenInvalid(): void {
  useAuthStore.getState().clearAuth()
  if (!isGuestPath(window.location.pathname)) {
    window.location.assign('/login')
  }
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
          // 1004（未通过校园认证）保留语义位：商品域（b2）启用，
          // 本批次用户域接口不出现该码，此处不做引导
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
