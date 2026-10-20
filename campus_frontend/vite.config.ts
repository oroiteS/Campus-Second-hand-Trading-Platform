import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// 本任务卡（b0fe）环境参数：
// - dev server 端口 5180（worktree 开发槽位 A），显式绑定 127.0.0.1
//   （联调一律用 127.0.0.1 字面地址；不显式绑定则 Node 可能只听 [::1]，127.0.0.1 连接被拒）
// - /api 与 /socket.io 代理到本批次后端 http://127.0.0.1:5010
//   代理目标只由 VITE_PROXY_TARGET 覆盖（loadEnv 读取），未设置时用批次默认值。
//   注意：VITE_API_BASE 是 axios baseURL（含 /api 后缀），不是代理目标，此处不得读取。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:5010'

  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5180,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
        '/socket.io': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
