import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// 本任务卡（b0fe）环境参数：
// - dev server 端口 5180（worktree 开发槽位 A）
// - /api 与 /socket.io 代理到本批次后端 http://127.0.0.1:5010
// 代理目标可用 VITE_API_BASE 覆盖（loadEnv 读取），未设置时用批次默认值。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_API_BASE || 'http://127.0.0.1:5010'

  return {
    plugins: [react()],
    server: {
      port: 5180,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
        '/socket.io': {
          target: backendTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
