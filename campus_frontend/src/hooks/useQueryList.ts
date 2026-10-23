import { useCallback, useEffect, useState } from 'react'

interface QueryListState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export interface QueryList<T> {
  data: T | null
  loading: boolean
  error: string | null
  retry: () => void
}

/**
 * 参数驱动的列表取数 hook（列表 / 搜索 / 我的商品 / 收藏共用）。
 *
 * - fetcher 须以 useCallback 按查询参数 memoize（本 hook 以其引用为依赖）；
 * - `enabled = false` 时不发请求（页面预检拦截后的「零请求」落实），
 *   初始 loading 随首帧 enabled 取值，避免永久骨架；
 * - 参数变化时保留旧数据直至新数据落盘（stale-while-revalidate），
 *   首次加载由初始 loading 承接骨架；重试在事件回调中递增 tick。
 */
export function useQueryList<T>(fetcher: () => Promise<T>, enabled = true): QueryList<T> {
  const [state, setState] = useState<QueryListState<T>>({
    data: null,
    loading: enabled,
    error: null,
  })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!enabled) {
      return
    }
    let cancelled = false
    fetcher()
      .then((result) => {
        if (cancelled) return
        setState({ data: result, loading: false, error: null })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof Error && err.message ? err.message : '请求失败，请稍后重试'
        setState((prev) => ({ data: prev.data, loading: false, error: message }))
      })
    return () => {
      cancelled = true
    }
  }, [fetcher, enabled, tick])

  const retry = useCallback(() => {
    setTick((prev) => prev + 1)
  }, [])

  return { data: state.data, loading: state.loading, error: state.error, retry }
}
