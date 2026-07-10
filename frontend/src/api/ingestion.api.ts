import { apiClient } from './client'
import type { DocumentIngestResponse, IngestionRunSummary } from './types'

export interface IngestionStatus {
  run_id:    string | null
  status:    'running' | 'completed' | 'failed' | null
  progress?: number
}

export const ingestionApi = {
  trigger: () =>
    apiClient.post<{ run_id: string; status: string }>('/ingestion/trigger').then((r) => r.data),

  getStatus: () =>
    apiClient.get<IngestionStatus>('/ingestion/status').then((r) => r.data),

  getRuns: () =>
    apiClient
      .get<{ runs: IngestionRunSummary[]; total: number; page: number; page_size: number }>('/ingestion/runs')
      .then((r) => r.data.runs),

  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<DocumentIngestResponse>('/ingestion/documents', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
}
