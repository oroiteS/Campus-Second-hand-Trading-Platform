import type { AuthApplication } from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockGetMyApplications, mockSubmitApplication } from './mock/certification'

/** 认证申请 multipart 表单字段（契约 requestBody：school_id / campus_id? / real_name / student_no / file） */
export interface CertificationSubmitForm {
  school_id: number
  /** 多校区学校必填；单校区学校必须省略 */
  campus_id?: number
  real_name: string
  student_no: string
  file: File
}

/** POST /api/certification/applications：提交认证申请（multipart；成功后 auth_status → pending） */
export function submitApplication(form: CertificationSubmitForm): Promise<AuthApplication> {
  if (USE_MOCK) {
    return mockSubmitApplication(form)
  }
  const formData = new FormData()
  formData.append('school_id', String(form.school_id))
  if (form.campus_id != null) {
    formData.append('campus_id', String(form.campus_id))
  }
  formData.append('real_name', form.real_name)
  formData.append('student_no', form.student_no)
  formData.append('file', form.file)
  return http.post<AuthApplication>('/certification/applications', formData).then((res) => res.data)
}

/** GET /api/certification/applications/mine：我的申请历史（created_at 倒序，不分页） */
export function getMyApplications(): Promise<AuthApplication[]> {
  if (USE_MOCK) {
    return mockGetMyApplications()
  }
  return http.get<AuthApplication[]>('/certification/applications/mine').then((res) => res.data)
}
