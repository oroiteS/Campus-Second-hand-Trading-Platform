import type { SchoolWithCampuses } from '../../types'
import { delay } from '../../utils/delay'

/**
 * GET /api/schools 契约同构 mock：仅启用状态的学校与校区，
 * 按名称排序，不分页。结构与 openapi.yaml SchoolWithCampuses 逐字段一致。
 */
export const MOCK_SCHOOLS: SchoolWithCampuses[] = [
  {
    id: 1,
    name: '示例大学',
    multi_campus: true,
    campuses: [
      { id: 1, school_id: 1, name: '东校区' },
      { id: 2, school_id: 1, name: '西校区' },
    ],
  },
  {
    id: 2,
    name: '示例学院',
    multi_campus: false,
    campuses: [{ id: 3, school_id: 2, name: '主校区' }],
  },
]

export function mockListSchools(): Promise<SchoolWithCampuses[]> {
  return delay(350).then(() =>
    MOCK_SCHOOLS.map((school) => ({
      ...school,
      campuses: school.campuses.map((campus) => ({ ...campus })),
    })),
  )
}
