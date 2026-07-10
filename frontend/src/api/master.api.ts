import { apiClient } from './client'

export interface TenantSummary {
  tenant_id:      string
  name:           string
  status:         'active' | 'suspended'
  itsm_provider:  string
  created_at:     string
  admin_email:    string | null
  user_count:     number
  setup_complete: boolean
}

export interface TenantCreate {
  name:               string
  admin_email:        string
  admin_display_name: string
}

export interface TenantCreateResponse {
  tenant:             TenantSummary
  admin_email:        string
  temporary_password: string
}

export interface TenantUpdate {
  name?:   string
  status?: 'active' | 'suspended'
}

export interface ResetTenantAdminResponse {
  admin_email:        string
  temporary_password: string
}

export const masterApi = {
  getTenants: () =>
    apiClient.get<TenantSummary[]>('/master/tenants').then((r) => r.data),
  createTenant: (data: TenantCreate) =>
    apiClient.post<TenantCreateResponse>('/master/tenants', data).then((r) => r.data),
  updateTenant: (tenantId: string, data: TenantUpdate) =>
    apiClient.patch<TenantSummary>(`/master/tenants/${tenantId}`, data).then((r) => r.data),
  resetTenantAdmin: (tenantId: string) =>
    apiClient.post<ResetTenantAdminResponse>(`/master/tenants/${tenantId}/reset-admin`).then((r) => r.data),
}
