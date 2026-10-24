import { useCallback, useEffect, useState } from 'react'

/** 请求键：fetcher 引用 + 重试计数；与最近落盘键不一致即表示「当前参数的请求尚未完成」 */
interface SettledKey<T> {
  fetcher: () => Promise<T>
  tick: number
}

interface QueryListState<T> {
  data: T | null
  error: string | null
  settled: SettledKey<T> | null
}

export interface QueryList<T> {
  data: T | null
  /** 骨架态：仅「当前参数没有任何已落盘数据」时为 true */
  loading: boolean
  /** 取数中（含参数变化后的 revalidate）；有旧数据时页面据此给弱加载提示，不闪骨架 */
  fetching: boolean
  error: string | null
  retry: () => void
}

/**
 * 参数驱动的列表取数 hook（列表 / 搜索 / 我的商品 / 收藏共用）。
 *
 * - fetcher 须以 useCallback 按查询参数 memoize（本 hook 以其引用为依赖）；
 * - `enabled = false` 时不发请求（页面预检拦截后的「零请求」落实），也不进入加载态；
 * - 参数变化：无数据 → 骨架；有数据 → 保留旧数据（stale-while-revalidate），
 *   由 `fetching` 提供可感知的更新信号（页面以 aria-busy / 文案消费）；
 * - 是否处于加载态由「当前请求键是否已落盘」在渲染期推导，避免导航后
 *   首帧出现「data 为空 + loading=false」的假空态；
 * - 错误随请求键落盘：重试（tick 递增）后旧错误立即消失，事件回调同步可见反馈。
 */
export function useQueryList<T>(fetcher: () => Promise<T>, enabled = true): QueryList<T> {
  const [state, setState] = useState<QueryListState<T>>({
    data: null,
    error: null,
    settled: null,
  })
  const [tick, setTick] = useState(0)

  const settled = state.settled
  const current = settled != null && settled.fetcher === fetcher && settled.tick === tick
  // enabled=false 时既不发请求也不显示加载态（避免永久骨架）
  const fetching = enabled && !current
  const loading = fetching && state.data == null

  useEffect(() => {
    if (!enabled) {
      return
    }
    let cancelled = false
    fetcher()
      .then((result) => {
        if (cancelled) return
        setState({ data: result, error: null, settled: { fetcher, tick } })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof Error && err.message ? err.message : '请求失败，请稍后重试'
        // 失败同样登记键：error 仅在与当前键匹配时暴露，保留旧数据供重试期间继续展示
        setState((prev) => ({ data: prev.data, error: message, settled: { fetcher, tick } }))
      })
    return () => {
      cancelled = true
    }
  }, [fetcher, enabled, tick])

  const retry = useCallback(() => {
    // 事件回调中同步清错并递增 tick：点击即离开错误态（无数据→骨架，有数据→fetching）
    setState((prev) => (prev.error == null ? prev : { ...prev, error: null }))
    setTick((prev) => prev + 1)
  }, [])

  return {
    data: state.data,
    loading,
    fetching,
    error: current ? state.error : null,
    retry,
  }
}
