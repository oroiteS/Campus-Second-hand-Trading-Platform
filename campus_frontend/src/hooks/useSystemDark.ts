import { useSyncExternalStore } from 'react'

const DARK_QUERY = '(prefers-color-scheme: dark)'

function subscribe(callback: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY)
  media.addEventListener('change', callback)
  return () => media.removeEventListener('change', callback)
}

/** 跟随系统暗色偏好（用于 antd 主题与令牌切换） */
export function useSystemDark(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(DARK_QUERY).matches,
    () => false,
  )
}
