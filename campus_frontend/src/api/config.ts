/**
 * 环境变量语义（前端仅有的两个构建期变量）：
 * - VITE_USE_MOCK：'true' 时 api 层切换到契约同构 mock
 * - VITE_API_BASE：axios 的 baseURL，是**含 /api 后缀的完整基址**（如 http://host:port/api）；
 *   留空 = 同源 '/api'，dev 下经 vite 代理转发到后端。
 *   注意：它不是 dev 代理目标。代理目标由 vite.config.ts 的 VITE_PROXY_TARGET 单独控制，
 *   二者不可混用（把代理地址写进本变量会让 axios 打到缺 /api 的根路径）。
 * 代码中不得出现其他接口地址来源。
 */
export const USE_MOCK: boolean = import.meta.env.VITE_USE_MOCK === 'true'

/** axios baseURL：可选的、带 /api 后缀的完整基址；未设置时为同源 '/api' */
export const API_BASE: string = import.meta.env.VITE_API_BASE || '/api'
