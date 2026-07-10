import { apiClient } from './client'
import type { LoginRequest, LoginResponse, UserPublic } from './types'

export const authApi = {
  login: (data: LoginRequest) =>
    apiClient.post<LoginResponse>('/auth/login', data).then((r) => r.data),

  refresh: () =>
    apiClient.post<{ access_token: string }>('/auth/refresh').then((r) => r.data),

  logout: () =>
    apiClient.post('/auth/logout'),

  me: () =>
    apiClient.get<UserPublic>('/auth/me').then((r) => r.data),

  changePassword: (data: { current_password: string; new_password: string }) =>
    apiClient.post('/auth/change-password', data).then((r) => r.data),
}
