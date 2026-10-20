import dayjs from 'dayjs'

/** ISO 8601（+08:00）→ 本地展示格式 */
export function formatDateTime(iso: string): string {
  return dayjs(iso).format('YYYY-MM-DD HH:mm:ss')
}

/** 探测延迟展示：null（不可用）显示占位符 */
export function formatLatency(ms: number | null | undefined): string {
  return ms == null ? '—' : `${ms} ms`
}
