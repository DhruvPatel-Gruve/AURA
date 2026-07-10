import { apiClient } from './client'
import type {
  SetupStatusResponse, JSMTestRequest, JSMTestResponse,
  ZendeskTestRequest, ZendeskTestResponse, WizardStepSave,
} from './types'

export const setupApi = {
  getStatus: () =>
    apiClient.get<SetupStatusResponse>('/setup/status').then((r) => r.data),

  testJSM: (data: JSMTestRequest) =>
    apiClient.post<JSMTestResponse>('/setup/test-jsm', data).then((r) => r.data),

  testZendesk: (data: ZendeskTestRequest) =>
    apiClient.post<ZendeskTestResponse>('/setup/test-zendesk', data).then((r) => r.data),

  saveStep: (data: WizardStepSave) =>
    apiClient.post<{ saved: boolean }>('/setup/wizard/save', data).then((r) => r.data),

  getProgress: () =>
    apiClient.get<{ steps: Record<number, Record<string, unknown>> }>('/setup/wizard/progress').then((r) => r.data),

  complete: () =>
    apiClient.post<{ launched: boolean }>('/setup/complete').then((r) => r.data),
}
