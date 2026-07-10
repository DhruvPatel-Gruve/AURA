import { apiClient } from './client'
import type { TicketSummary, LowConfQueueEntry, TicketDetail, MyTicketSummary } from './types'

export const ticketsApi = {
  // ── All processed tickets from audit_log (paginated) ─────────────────────
  list: (params?: {
    page?: number; page_size?: number
    category?: string; action_taken?: string; status?: string; ticket_id?: string; team_id?: string
  }) =>
    apiClient
      .get<{ items: TicketSummary[]; total: number; page: number; page_size: number }>('/tickets', { params })
      .then((r) => r.data),

  // ── End-user's own submitted tickets ──────────────────────────────────────
  getMine: () =>
    apiClient.get<MyTicketSummary[]>('/tickets/mine').then((r) => r.data),

  // ── Low-confidence / duplicate review queue ───────────────────────────────
  // Returns all unresolved low_confidence_queue entries
  getQueue: (params?: { team_id?: string; category?: string }) =>
    apiClient
      .get<LowConfQueueEntry[]>('/tickets/queue', { params })
      .then((r) => r.data),

  // ── Ticket detail from audit_log (includes current assignment) ───────────
  getTicket: (ticketId: string) =>
    apiClient.get<TicketDetail>(`/tickets/${ticketId}`).then((r) => r.data),

  // ── Assignment acknowledgment ──────────────────────────────────────────────
  // Ticket assignment is automatic (assignment_node); acknowledging just
  // confirms a human has seen it, cancelling the reassignment timer.
  acknowledgeTicket: (ticketId: string) =>
    apiClient.post<{ ok: boolean }>(`/tickets/${ticketId}/acknowledge`).then((r) => r.data),

  // ── Rollback / re-post a comment directly on a ticket ─────────────────────
  rollbackComment: (ticketId: string) =>
    apiClient.post<{ ok: boolean }>(`/tickets/${ticketId}/rollback-comment`).then((r) => r.data),

  postComment: (ticketId: string, editedComment: string) =>
    apiClient
      .post<{ jsm_comment_id: string; posted_at: string }>(`/tickets/${ticketId}/comment`, {
        edited_comment: editedComment,
      })
      .then((r) => r.data),

  // ── Queue item actions (use queue_id, not ticket_id) ──────────────────────
  approveQueueItem: (queueId: string) =>
    apiClient
      .post<{ jsm_comment_id: string; posted_at: string }>(`/tickets/queue/${queueId}/approve`)
      .then((r) => r.data),

  rejectQueueItem: (queueId: string, reason: string) =>
    apiClient
      .post<{ ok: boolean }>(`/tickets/queue/${queueId}/reject`, { reason })
      .then((r) => r.data),

  editQueueItem: (queueId: string, editedComment: string) =>
    apiClient
      .post<{ jsm_comment_id: string; posted_at: string }>(`/tickets/queue/${queueId}/edit`, {
        edited_comment: editedComment,
      })
      .then((r) => r.data),

  // ── End-user ticket submit ────────────────────────────────────────────────
  submitTicket: (data: { summary: string; description: string; category_hint?: string }) =>
    apiClient.post<{ ticket_id: string; message: string }>('/tickets/submit', data).then((r) => r.data),
}
