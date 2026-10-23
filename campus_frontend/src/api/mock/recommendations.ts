import type { HomeFeedData } from '../../types'
import { delay } from '../../utils/delay'
import { recommendationCandidates, toProductSummary } from './products'
import { requireVerifiedSession } from './users'

/**
 * GET /api/recommendations/home 契约同构 mock（≤ 40 条，排除自己发布）。
 *
 * - 冷启动（无画像）与画像态（32 画像召回 + 8 随机补足）对前端不可区分——
 *   mock 统一回全量候选的轮转窗口，前端无感知（任务卡场景要求）；
 * - `refresh=true`（「换一批」）窗口前移 40，候选不足时环绕取整；
 * - 降级样例演示：连续换一批的第 3 次（refreshCount % 3 === 0）返回
 *   `degraded: true` + `degraded_reason`（DegradedBanner 演示，任务卡降级样例）；
 * - 管理员：空列表 200（契约：无推荐语义）。
 */

/** 轮转窗口起点（refresh 时前移） */
let feedCursor = 0

let refreshCount = 0

export function mockGetHomeFeed(refresh?: boolean): Promise<HomeFeedData> {
  return delay(450).then(() => {
    const user = requireVerifiedSession()
    if (user.role === 'admin') {
      return { items: [] }
    }
    const candidates = recommendationCandidates(user.id)
    if (candidates.length === 0) {
      return { items: [] }
    }
    if (refresh) {
      refreshCount += 1
      feedCursor = (feedCursor + 40) % candidates.length
    }
    const items = []
    for (let i = 0; i < Math.min(40, candidates.length); i += 1) {
      items.push(toProductSummary(candidates[(feedCursor + i) % candidates.length]))
    }
    const degraded = refresh === true && refreshCount % 3 === 0
    return {
      items,
      ...(degraded
        ? { degraded: true as const, degraded_reason: '向量服务不可用，已降级为随机推荐' }
        : {}),
    }
  })
}
