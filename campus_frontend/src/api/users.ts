import type {
  PasswordChangeInput,
  ProfileUpdateInput,
  UserProfile,
} from '../types'
import { USE_MOCK } from './config'
import { http } from './http'
import { mockChangePassword, mockGetMe, mockUpdateMe, mockUploadAvatar } from './mock/users'

/** GET /api/users/me：当前登录用户完整资料（个人中心首屏） */
export function getMe(): Promise<UserProfile> {
  if (USE_MOCK) {
    return mockGetMe()
  }
  return http.get<UserProfile>('/users/me').then((res) => res.data)
}

/** PUT /api/users/me：更新资料（三字段可选，仅更新出现的字段；phone 空串 = 清除） */
export function updateMe(body: ProfileUpdateInput): Promise<UserProfile> {
  if (USE_MOCK) {
    return mockUpdateMe(body)
  }
  return http.put<UserProfile>('/users/me', body).then((res) => res.data)
}

/** PUT /api/users/me/password：修改密码（原密码错误 2003；强度同注册规则） */
export function changePassword(body: PasswordChangeInput): Promise<void> {
  if (USE_MOCK) {
    return mockChangePassword(body.old_password, body.new_password)
  }
  return http.put<void>('/users/me/password', body).then(() => undefined)
}

/** POST /api/users/me/avatar：上传头像（multipart/form-data，字段 file） */
export function uploadAvatar(file: File): Promise<UserProfile> {
  if (USE_MOCK) {
    return mockUploadAvatar(file)
  }
  const formData = new FormData()
  formData.append('file', file)
  return http.post<UserProfile>('/users/me/avatar', formData).then((res) => res.data)
}
