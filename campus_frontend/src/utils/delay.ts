/** 等待指定毫秒（mock 延迟模拟用） */
export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}
