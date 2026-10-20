import { useCallback, useEffect, useState } from 'react'

interface AsyncDataState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

export interface AsyncData<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * 页面取数 hook：加载 / 错误（含重试）/ 正常三态。
 * fetcher 需为稳定引用（通常传 api 模块级函数）；
 * 首次加载由初始状态承接，重试在事件回调中置位，effect 内仅异步落盘。
 */
export function useAsyncData<T>(fetcher: () => Promise<T>): AsyncData<T> {
  const [state, setState] = useState<AsyncDataState<T>>({
    data: null,
    error: null,
    loading: true,
  })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetcher()
      .then((result) => {
        if (cancelled) return
        setState({ data: result, error: null, loading: false })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof Error && err.message ? err.message : '请求失败，请稍后重试'
        setState((prev) => ({ ...prev, error: message, loading: false }))
      })
    return () => {
      cancelled = true
    }
  }, [fetcher, tick])

  const reload = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true, error: null }))
    setTick((prev) => prev + 1)
  }, [])

  return { data: state.data, loading: state.loading, error: state.error, reload }
}
