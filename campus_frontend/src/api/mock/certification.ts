import type { AuthApplication, CampusRef } from '../../types'
import { delay } from '../../utils/delay'
import { validateRealName, validateUploadFile } from '../../utils/validators'
import { ApiError } from '../http'
import type { CertificationSubmitForm } from '../certification'
import { getMockCurrentUser, MOCK_ACCOUNTS, nextImageId, nowIso } from './users'
import { MOCK_SCHOOLS } from './schools'

/**
 * mock 认证申请历史（按用户 id 存储，unshift 插入即 created_at 倒序）。
 * 预置：student02 一条 approved（历史徽章演示）、student03 一条 rejected
 * （含 reject_reason，供认证状态页演示驳回展示与重提）。
 */
const APPLICATIONS_BY_USER = new Map<number, AuthApplication[]>()

function seedApplications(): void {
  const student02 = MOCK_ACCOUNTS.find((account) => account.profile.id === 1002)
  const student03 = MOCK_ACCOUNTS.find((account) => account.profile.id === 1003)
  if (student02) {
    APPLICATIONS_BY_USER.set(student02.profile.id, [
      {
        id: 5,
        school: { id: 1, name: '示例大学', multi_campus: true },
        campus: { id: 1, school_id: 1, name: '东校区' },
        student_no: student02.profile.student_no,
        real_name: '李明',
        student_card: { id: 21, url: '/api/images/21' },
        status: 'approved',
        reject_reason: null,
        reviewed_at: '2026-09-10T10:00:00+08:00',
        created_at: '2026-09-09T14:00:00+08:00',
      },
    ])
  }
  if (student03) {
    APPLICATIONS_BY_USER.set(student03.profile.id, [
      {
        id: 8,
        school: { id: 1, name: '示例大学', multi_campus: true },
        campus: { id: 2, school_id: 1, name: '西校区' },
        student_no: student03.profile.student_no,
        real_name: '王华',
        student_card: { id: 31, url: '/api/images/31' },
        status: 'rejected',
        reject_reason: '学生证照片模糊，无法核对学号',
        reviewed_at: '2026-10-19T10:00:00+08:00',
        created_at: '2026-10-19T09:30:00+08:00',
      },
    ])
  }
}

seedApplications()

let nextApplicationIdSeed = 20

function nextApplicationId(): number {
  nextApplicationIdSeed += 1
  return nextApplicationIdSeed
}

/**
 * POST /api/certification/applications：
 * 9003（pending/approved 重复提交、管理员提交）→ 9001 字段级
 * （学校/校区/姓名/学号一致/文件）→ 成功置用户 auth_status = pending。
 */
export function mockSubmitApplication(form: CertificationSubmitForm): Promise<AuthApplication> {
  return delay(600).then(() => {
    const user = getMockCurrentUser()
    if (!user) {
      throw new ApiError(1001, '令牌缺失或无效', null)
    }
    if (user.role === 'admin') {
      throw new ApiError(9003, '管理员账号无需校园认证', null)
    }
    if (user.auth_status === 'pending' || user.auth_status === 'approved') {
      throw new ApiError(9003, '当前状态不允许提交认证申请', null)
    }
    const fields: Record<string, string> = {}
    const school = MOCK_SCHOOLS.find((item) => item.id === form.school_id)
    let campusRef: CampusRef | null = null
    if (!school) {
      fields.school_id = '学校不存在或已停用'
    } else if (school.multi_campus) {
      const campus =
        form.campus_id == null
          ? undefined
          : school.campuses.find((item) => item.id === form.campus_id)
      if (form.campus_id == null) {
        fields.campus_id = '多校区学校必须选择校区'
      } else if (!campus) {
        fields.campus_id = '所选校区不存在或已停用'
      } else {
        campusRef = { ...campus }
      }
    } else if (form.campus_id != null) {
      fields.campus_id = '单校区学校须省略校区'
    }
    const realNameError = validateRealName(form.real_name)
    if (realNameError) fields.real_name = realNameError
    if (form.student_no !== user.student_no) {
      fields.student_no = '学号须与注册学号完全一致'
    }
    const fileError = validateUploadFile(form.file, '学生证照片')
    if (fileError) fields.file = fileError
    if (Object.keys(fields).length > 0) {
      throw new ApiError(9001, '参数校验失败', { fields })
    }
    if (!school) {
      // 上面 fields 已含 school_id 错误，此处仅为类型收窄
      throw new ApiError(9001, '参数校验失败', { fields })
    }
    const imageId = nextImageId()
    const application: AuthApplication = {
      id: nextApplicationId(),
      school: { ...school },
      campus: campusRef,
      student_no: form.student_no,
      real_name: form.real_name,
      student_card: { id: imageId, url: `/api/images/${imageId}` },
      status: 'pending',
      reject_reason: null,
      reviewed_at: null,
      created_at: nowIso(),
    }
    user.auth_status = 'pending'
    const history = APPLICATIONS_BY_USER.get(user.id) ?? []
    history.unshift(application)
    APPLICATIONS_BY_USER.set(user.id, history)
    return structuredClone(application)
  })
}

/** GET /api/certification/applications/mine：当前用户全部申请，created_at 倒序，不分页 */
export function mockGetMyApplications(): Promise<AuthApplication[]> {
  return delay(350).then(() => {
    const user = getMockCurrentUser()
    if (!user) {
      throw new ApiError(1001, '令牌缺失或无效', null)
    }
    const history = APPLICATIONS_BY_USER.get(user.id) ?? []
    return structuredClone(history)
  })
}
