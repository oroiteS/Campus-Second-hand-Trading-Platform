/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'true' 时 api 层走契约同构 mock；联调前须置 false 或留空 */
  readonly VITE_USE_MOCK?: string
  /** axios 基址（含 /api 后缀）；留空 = 同源 /api */
  readonly VITE_API_BASE?: string
  /** 仅 dev server 的代理目标，不进入构建产物（vite.config.ts 读取） */
  readonly VITE_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
