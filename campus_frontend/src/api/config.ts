/**
 * 环境开关（前端仅有的两个环境变量）：
 * - VITE_USE_MOCK：'true' 时 api 层切换到契约同构 mock
 * - VITE_API_BASE：API 地址；留空走 vite 代理（同源 /api）
 * 代码中不得出现其他接口地址来源。
 */
export const USE_MOCK: boolean = import.meta.env.VITE_USE_MOCK === 'true'

export const API_BASE: string = import.meta.env.VITE_API_BASE || '/api'
