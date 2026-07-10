// ── Auth ─────────────────────────────────────────────────────────────────────
export interface LoginRequest {
  email:    string
  password: string
}

export interface LoginResponse {
  access_token:   string
  token_type:     string
  role:           string
  user_id:        string
  setup_complete: boolean
}

// ── User ─────────────────────────────────────────────────────────────────────
export interface UserPublic {
  user_id:         string
  email:           string
  display_name:    string
  role:            string
  team_id:         string | null
  is_active:       boolean
  last_login:      string | null
  jira_account_id: string | null
}

export interface UserCreate {
  email:            string
  display_name:     string
  password:         string
  role:             string
  team_id?:         string
  jira_account_id?: string
}

export interface UserUpdate {
  email?:           string
  display_name?:    string
  role?:            string
  team_id?:         string
  is_active?:       boolean
  jira_account_id?: string
}

// ── Setup ─────────────────────────────────────────────────────────────────────
export interface SetupStatusResponse {
  setup_complete:  boolean
  current_step:    number
}

export interface JSMTestRequest {
  base_url:   string
  api_token:  string
  user_email: string
  project_key:string
}

export interface JSMTestResponse {
  success:      boolean
  ticket_count: number
  error:        string | null
}

export interface ZendeskTestRequest {
  subdomain: string
  api_email: string
  api_token: string
}

export interface ZendeskTestResponse {
  success:      boolean
  ticket_count: number
  error?:       string
}

export interface WizardStepSave {
  step: number
  data: Record<string, unknown>
}

// ── Platform Config ───────────────────────────────────────────────────────────
export interface PlatformConfig {
  aura_enabled:               boolean
  confidence_threshold:        number
  abstention_threshold:        number
  conversation_idle_timeout_hours: number
  polling_interval_minutes:    number
  ingestion_interval_hours:    number
  collision_timeout_minutes:   number
  assignment_timeout_minutes:  number
  last_poll_timestamp:         string | null
  last_sync_timestamp:         string | null
  setup_complete:              boolean
  current_wizard_step:         number
  kill_switch_changed_by:      string | null
  kill_switch_changed_at:      string | null
  accent_color:                string | null   // hex, e.g. "#6366f1"
}

// ── Category Config ───────────────────────────────────────────────────────────
export interface CategoryConfig {
  category_id:          string
  name:                 string
  auto_comment_enabled: boolean
  sla_minutes:          number
  team_id:              string
}

// ── Tickets ──────────────────────────────────────────────────────────────────
export interface TicketSummary {
  ticket_id:        string
  summary:          string
  category:         string | null
  priority:         string | null
  status:           string | null   // live ITSM workflow status (Open / In Progress / Resolved)
  sla_deadline:     string | null
  sla_status:       'ok' | 'warning' | 'breached' | null
  action_taken:     string | null
  claimed_by:       string | null
  abstained:            boolean
  confidence_score:     number | null
  auto_comment_enabled: boolean | null
  assigned_to:          string | null
  acknowledged_at:      string | null
  team_id:              string | null   // the category's owning team
}

export interface AuditStep {
  node_name:  string
  timestamp:  string
  decision:   string
  metadata:   Record<string, unknown>
}

export interface TicketComment {
  author:  string
  body:    string
  created: string
}

export interface TicketDetail {
  ticket_id:                   string
  summary:                     string | null   // the original question the reporter asked
  description:                 string | null
  action_taken:                string
  priority:                    string | null
  category:                    string | null
  status:                      string | null   // live ITSM workflow status
  auto_comment_enabled:        boolean | null
  confidence_score:            number | null
  abstained:                   boolean
  jsm_comment_id:               string | null
  comments:                    TicketComment[]   // live comment thread — visible regardless of status
  rollback_action_id:          string | null     // set when there's a posted comment that can still be rolled back
  audit_steps:                 AuditStep[]
  created_at:                  string
  assigned_to:                 string | null
  assigned_at:                 string | null
  acknowledged_at:             string | null
  assignment_timeout_minutes:  number
}

export interface MyTicketSummary {
  ticket_id:        string
  submitted_at:     string
  status:           string   // live ITSM status when known, else a synthetic 'open'|'reviewing'|'resolved'
  abstained:        boolean
  confidence_score: number | null
  processed_at:     string | null
}

export interface LowConfQueueEntry {
  queue_id:          string
  ticket_id:         string
  summary:           string
  category:          string | null
  confidence_score:  number
  formatted_comment: string
  citations:         string[]
  abstained:         boolean
  queued_at:         string
  team_id:           string | null   // owning team — technicians can only act on their own
}


// ── Dashboard ─────────────────────────────────────────────────────────────────
export interface SystemHealthResponse {
  api_uptime_seconds:       number
  gemini_latency_ms:        number
  qdrant_query_ms:          number
  ws_connections:           number
  jsm_poll_last_run:        string | null
  jsm_poll_next_run:        string | null
  scheduler_running:        boolean
  polling_interval_minutes: number
}

export interface TechnicianStats {
  queue_count:       number
  low_conf_pending:  number
  sla_breach_count:  number
}

// ── Documents ─────────────────────────────────────────────────────────────────
export interface DocumentSummary {
  doc_id:       string
  filename:     string
  chunk_count:  number
  uploaded_at:  string | null
}

export interface DocumentIngestResponse {
  doc_id:         string
  filename:       string
  chunks_created: number
  message:        string
}

// ── Ingestion ─────────────────────────────────────────────────────────────────
export interface IngestionRunSummary {
  run_id:           string
  started_at:       string
  completed_at:     string | null
  tickets_fetched:  number
  tickets_indexed:  number
  tickets_skipped:  number
  chunks_created:   number
  status:           'running' | 'completed' | 'failed'
  error_message:    string | null
}

// ── Audit / Rollback ──────────────────────────────────────────────────────────
export interface AuditEntry {
  entry_id:         string
  ticket_id:        string
  action_taken:     string
  priority:             string | null
  category:             string | null
  auto_comment_enabled: boolean | null
  confidence_score:     number | null
  abstained:            boolean
  jsm_comment_id:       string | null
  rollback_ref:         string | null
  audit_steps:      string
  created_at:       string
}

export interface RollbackRecord {
  action_id:       string
  ticket_id:       string
  action_type:     string
  actor:           string
  created_at:      string
  rolled_back_at:  string | null
  rolled_back_by:  string | null
}

// ── Chat ─────────────────────────────────────────────────────────────────────
export interface ChatMessage {
  role:       'user' | 'assistant'
  content:    string
  timestamp:  string
  citations?: string[]
}

export interface ChatResponse {
  reply:      string
  citations:  string[]
  timestamp:  string
  session_id: string
}

export interface ChatHistoryResponse {
  messages:   ChatMessage[]
  session_id: string | null
}

// ── WebSocket event envelope ──────────────────────────────────────────────────
export interface WSEvent<T = Record<string, unknown>> {
  event_type: string
  payload:    T
  timestamp:  string
}

// ── Notification (client-side) ────────────────────────────────────────────────
export interface Notification {
  id:          string
  event_type:  string
  message:     string
  timestamp:   string
  read:        boolean
}
