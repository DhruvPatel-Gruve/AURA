import { apiClient } from './client'
import type { SystemHealthResponse, TechnicianStats } from './types'

export interface ManagerSLAData {
  compliance_by_category: Array<{ category: string; compliance_pct: number }>
  breach_history:         Array<{ ticket_id: string; category: string; breached_at: string }>
  upcoming_deadlines:     Array<{ ticket_id: string; summary: string; deadline: string; category: string }>
}

export interface ManagerResolutionData {
  auto_pct:           number
  manual_pct:         number
  first_contact_rate: number
  trend_data:         Array<{ date: string; auto_pct: number }>
}

export interface ManagerConfidenceData {
  avg_by_category:   Array<{ category: string; avg_score: number }>
  histogram_buckets: Array<{ bucket: string; count: number }>
  trend_data:        Array<{ date: string; avg_score: number }>
}

export interface ManagerTeamMember {
  technician_id:   string
  name:            string
  ticket_count:    number
  avg_claim_ms:    number
  correction_rate: number
}

export interface ManagerAbstentionItem {
  category:        string
  abstention_rate: number
  abstained_count:  number
  gap_severity:    'low' | 'medium' | 'high'
}

export interface ManagerCollisionsData {
  collision_events: Array<{ ticket_id: string; claimants: string[]; created_at: string }>
}

export interface ManagerCostSavingsData {
  hours_saved:        number
  cost_reduction:     number
  zero_touch_per_week: number
  trend_data:          Array<{ date: string; zero_touch: number }>
}

export interface ManagerApprovalItem {
  queue_id:          string
  ticket_id:         string
  confidence_score:  number | null
  abstained:         boolean
  team_id:           string | null
  queued_at:         string
}

export interface ManagerApprovalsResponse {
  items:     ManagerApprovalItem[]
  total:     number
  page:      number
  page_size: number
}

export interface ManagerApprovalsParams {
  team_id?:        string
  status?:         'abstained' | 'low_confidence'
  min_confidence?: number
  sort_by?:        'queued_at' | 'confidence_score' | 'team_id'
  sort_dir?:       'asc' | 'desc'
  page?:           number
  page_size?:      number
}

// ── Ticket Tree ──────────────────────────────────────────────────────────────

export type TreeGroupBy = 'category_status' | 'team_category' | 'priority_sla'

export interface TreeNodeStats {
  total:              number
  auto_resolved:      number
  human_resolved:     number
  in_review:          number
  abstained:          number
  breached:           number
  warning:            number
  sla_compliance_pct: number | null
  avg_confidence:     number | null
}

export interface TreeBucket extends TreeNodeStats {
  key:   string
  label: string
}

export interface TreeGroup extends TreeNodeStats {
  key:     string
  label:   string
  buckets: TreeBucket[]
}

export interface TicketTreeResponse {
  group_by: TreeGroupBy
  root:     TreeNodeStats & { groups: TreeGroup[] }
  generated_at: string
}

export interface TreeLeafTicket {
  ticket_id:        string
  category:         string
  team:             string
  priority:         string
  resolution_state: string
  sla_state:        'breached' | 'warning' | 'ok' | 'none'
  sla_deadline:     string | null
  workflow_status:  string | null
  confidence_score: number | null
  assignee_name:    string | null
  acknowledged:     boolean
  created_at:       string
}

export interface TreeLeavesResponse {
  items:     TreeLeafTicket[]
  total:     number
  page:      number
  page_size: number
}

type DateRange = { date_from?: string; date_to?: string }

export const dashboardApi = {
  getAdminHealth: () =>
    apiClient.get<SystemHealthResponse>('/dashboard/admin/health').then((r) => r.data),

  getManagerSLA: (params?: DateRange & { category?: string }) =>
    apiClient.get<ManagerSLAData>('/dashboard/manager/sla', { params }).then((r) => r.data),

  getManagerResolution: (params?: DateRange) =>
    apiClient.get<ManagerResolutionData>('/dashboard/manager/resolution', { params }).then((r) => r.data),

  getManagerConfidence: (params?: DateRange) =>
    apiClient.get<ManagerConfidenceData>('/dashboard/manager/confidence', { params }).then((r) => r.data),

  getManagerTeam: (params?: DateRange) =>
    apiClient.get<ManagerTeamMember[]>('/dashboard/manager/team', { params }).then((r) => r.data),

  getManagerAbstention: (params?: DateRange & { sort_by?: 'rate' | 'count' }) =>
    apiClient.get<ManagerAbstentionItem[]>('/dashboard/manager/abstention', { params }).then((r) => r.data),

  getManagerCollisions: (params?: DateRange) =>
    apiClient.get<ManagerCollisionsData>('/dashboard/manager/collisions', { params }).then((r) => r.data),

  getManagerCostSavings: (params?: DateRange) =>
    apiClient.get<ManagerCostSavingsData>('/dashboard/manager/cost-savings', { params }).then((r) => r.data),

  getManagerApprovals: (params?: ManagerApprovalsParams) =>
    apiClient.get<ManagerApprovalsResponse>('/dashboard/manager/approvals', { params }).then((r) => r.data),

  getTechnicianStats: () =>
    apiClient.get<TechnicianStats>('/dashboard/technician/stats').then((r) => r.data),

  getTicketTree: (params?: DateRange & { group_by?: TreeGroupBy }) =>
    apiClient.get<TicketTreeResponse>('/dashboard/manager/ticket-tree', { params }).then((r) => r.data),

  getTicketTreeTickets: (params: DateRange & {
    group_by: TreeGroupBy; group: string; bucket: string; page?: number; page_size?: number
  }) =>
    apiClient.get<TreeLeavesResponse>('/dashboard/manager/ticket-tree/tickets', { params }).then((r) => r.data),
}
