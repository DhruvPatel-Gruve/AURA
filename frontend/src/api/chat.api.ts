import { apiClient } from './client'
import type { ChatMessage, ChatResponse, ChatHistoryResponse } from './types'

export type { ChatMessage, ChatResponse, ChatHistoryResponse }

export const chatApi = {
  send: (message: string) =>
    apiClient.post<ChatResponse>('/chat', { message }).then((r) => r.data),

  getHistory: () =>
    apiClient.get<ChatHistoryResponse>('/chat/history').then((r) => r.data),

  close: () =>
    apiClient.post<{ closed: boolean }>('/chat/close').then((r) => r.data),
}
