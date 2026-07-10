import { apiClient } from './client'
import type {
  UserPublic, UserCreate, UserUpdate,
  CategoryConfig, PlatformConfig,
  RollbackRecord, AuditEntry, SystemHealthResponse,
  DocumentSummary,
} from './types'

interface CategoryCreate {
  name:                 string
  auto_comment_enabled: boolean
  sla_minutes:          number
  team_id:              string
}

export const adminApi = {
  // ── Categories ────────────────────────────────────────────────────────────
  getCategories: () =>
    apiClient.get<CategoryConfig[]>('/admin/categories').then((r) => r.data),
  createCategory: (data: CategoryCreate) =>
    apiClient.post<CategoryConfig>('/admin/categories', data).then((r) => r.data),
  updateCategory: (id: string, data: Partial<CategoryCreate>) =>
    apiClient.patch<CategoryConfig>(`/admin/categories/${id}`, data).then((r) => r.data),
  deleteCategory: (id: string) =>
    apiClient.delete(`/admin/categories/${id}`).then((r) => r.data),

  // ── Users ─────────────────────────────────────────────────────────────────
  getUsers: () =>
    apiClient.get<UserPublic[]>('/admin/users').then((r) => r.data),
  createUser: (data: UserCreate) =>
    apiClient.post<UserPublic>('/admin/users', data).then((r) => r.data),
  updateUser: (id: string, data: UserUpdate) =>
    apiClient.patch<UserPublic>(`/admin/users/${id}`, data).then((r) => r.data),
  deleteUser: (id: string) =>
    apiClient.delete(`/admin/users/${id}`).then((r) => r.data),

  // ── Platform config ────────────────────────────────────────────────────────
  getConfig: () =>
    apiClient.get<PlatformConfig>('/admin/config').then((r) => r.data),
  updateConfig: (data: Partial<PlatformConfig>) =>
    apiClient.put<PlatformConfig>('/admin/config', data).then((r) => r.data),

  // ── Kill switch ────────────────────────────────────────────────────────────
  getKillSwitch: () =>
    apiClient
      .get<{ enabled: boolean; changed_by: string | null; changed_at: string | null }>('/admin/kill-switch')
      .then((r) => r.data),
  enableKillSwitch:  () => apiClient.post('/admin/kill-switch/enable').then((r) => r.data),
  disableKillSwitch: () => apiClient.post('/admin/kill-switch/disable').then((r) => r.data),

  // ── Rollback ───────────────────────────────────────────────────────────────
  getRollbackHistory: (params?: Record<string, string | number>) =>
    apiClient
      .get<{ items: RollbackRecord[]; total: number; page: number; pages: number }>('/admin/rollback', { params })
      .then((r) => r.data),
  triggerRollback: (actionId: string) =>
    apiClient.post(`/admin/rollback/${actionId}`).then((r) => r.data),

  // ── Audit log ─────────────────────────────────────────────────────────────
  getAuditLog: (params?: Record<string, string | number>) =>
    apiClient
      .get<{ items: AuditEntry[]; total: number; page: number; pages: number }>('/admin/audit-log', { params })
      .then((r) => ({ entries: r.data.items, total: r.data.total })),
  exportAuditLogCSV: (params?: Record<string, string>) =>
    apiClient
      .get<Blob>('/admin/audit-log/export', { params, responseType: 'blob' })
      .then((r) => r.data),

  // ── Qdrant ────────────────────────────────────────────────────────────────
  getQdrantStats: () =>
    apiClient.get<Record<string, unknown>>('/admin/qdrant/stats').then((r) => r.data),
  triggerReingestion: () =>
    apiClient.post('/admin/qdrant/trigger-ingestion').then((r) => r.data),
  rebuildIndex: () =>
    apiClient.post('/admin/qdrant-rebuild').then((r) => r.data),

  // ── Documents ─────────────────────────────────────────────────────────────
  getDocuments: () =>
    apiClient.get<{ documents: DocumentSummary[] }>('/admin/documents').then((r) => r.data.documents),
  deleteDocument: (docId: string) =>
    apiClient.delete(`/admin/documents/${docId}`).then((r) => r.data),

  // ── System health ─────────────────────────────────────────────────────────
  getSystemHealth: () =>
    apiClient.get<SystemHealthResponse>('/admin/system-health').then((r) => r.data),
}
