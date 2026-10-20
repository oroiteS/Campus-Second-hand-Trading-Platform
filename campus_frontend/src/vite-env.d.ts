/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'true' 时 api 层走契约同构 mock */
  readonly VITE_USE_MOCK?: string
  /** API 服务地址；留空走 vite 代理（同源 /api） */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
