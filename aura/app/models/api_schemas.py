"""API request and response schemas for all routes.

These are the wire-format contracts between the FastAPI backend and the React
frontend. They mirror the TypeScript interfaces in frontend/src/api/types.ts.
"""

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Authentication ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    setup_complete: bool


class TokenRefreshResponse(BaseModel):
    access_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)


# ── Setup wizard ──────────────────────────────────────────────────────────────

class SetupStatusResponse(BaseModel):
    setup_complete: bool
    current_step: int


class JSMTestRequest(BaseModel):
    base_url: str = Field(..., min_length=8, max_length=500)
    api_token: str = Field(..., min_length=1, max_length=1000)
    user_email: str = Field(..., min_length=3, max_length=255)
    project_key: str = Field(..., min_length=1, max_length=50)


class JSMTestResponse(BaseModel):
    success: bool
    ticket_count: int = 0
    error: str | None = None


class ZendeskTestRequest(BaseModel):
    subdomain: str = Field(..., min_length=1, max_length=255)
    api_email: str = Field(..., min_length=3, max_length=255)
    api_token: str = Field(..., min_length=1, max_length=1000)


class ZendeskTestResponse(BaseModel):
    success: bool
    ticket_count: int = 0
    error: str | None = None


_MAX_WIZARD_STEP_DATA_BYTES = 100_000


class WizardStepSave(BaseModel):
    step: int = Field(..., ge=1, le=9)
    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def _bound_data_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        # dict[str, Any] has no natural size limit — without this, a wizard
        # step save is an unauthenticated-adjacent (admin-only, but still)
        # unbounded-JSON-blob storage primitive.
        size = len(json.dumps(v))
        if size > _MAX_WIZARD_STEP_DATA_BYTES:
            raise ValueError(f"Step data too large ({size} bytes, max {_MAX_WIZARD_STEP_DATA_BYTES})")
        return v


class WizardProgressResponse(BaseModel):
    steps: dict[int, dict[str, Any]]   # step_number -> step_data


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=8, max_length=256)
    role: Literal["admin", "manager", "technician", "end_user", "enduser"]
    team_id: str | None = Field(None, max_length=100)
    jira_account_id: str | None = Field(None, max_length=200)


class UserUpdate(BaseModel):
    email: str | None = Field(None, min_length=3, max_length=255)
    password: str | None = Field(None, min_length=8, max_length=256)
    display_name: str | None = Field(None, min_length=1, max_length=200)
    role: Literal["admin", "manager", "technician", "end_user", "enduser"] | None = None
    team_id: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    jira_account_id: str | None = Field(None, max_length=200)


class UserPublic(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    team_id: str | None = None
    is_active: bool
    last_login: datetime | None = None
    jira_account_id: str | None = None


# ── Categories ────────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    auto_comment_enabled: bool = False
    sla_minutes: int = Field(480, ge=1, le=525_600)  # capped at 1 year
    team_id: str = Field(..., max_length=100)


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    auto_comment_enabled: bool | None = None
    sla_minutes: int | None = Field(None, ge=1, le=525_600)
    team_id: str | None = Field(None, max_length=100)


class CategoryResponse(BaseModel):
    category_id: str
    name: str
    auto_comment_enabled: bool
    sla_minutes: int
    team_id: str


# ── Tickets ───────────────────────────────────────────────────────────────────

class TicketSummary(BaseModel):
    ticket_id: str
    summary: str
    category: str | None = None
    priority: str | None = None
    status: str | None = None           # live Jira workflow status (Open/In Progress/Resolved)
    sla_deadline: str | None = None     # ISO-8601
    sla_status: str | None = None       # "ok" | "warning" | "breached"
    action_taken: str | None = None
    claimed_by: str | None = None
    abstained: bool = False
    confidence_score: float | None = None
    auto_comment_enabled: bool | None = None
    assigned_to: str | None = None
    acknowledged_at: str | None = None
    team_id: str | None = None   # the category's owning team — technicians can only act on their own


class LowConfQueueEntry(BaseModel):
    queue_id: str
    ticket_id: str
    summary: str
    category: str | None = None
    confidence_score: float | None = None
    formatted_comment: str
    citations: list[str] = Field(default_factory=list)
    abstained: bool = False
    queued_at: datetime
    team_id: str | None = None   # owning team — technicians can only act on their own


class TicketSubmit(BaseModel):
    summary: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=10_000)
    category_hint: str | None = Field(None, max_length=100)


class SuggestionApproveResponse(BaseModel):
    jsm_comment_id: str
    posted_at: datetime


class SuggestionRejectRequest(BaseModel):
    reason: str = Field(..., max_length=2000)


class SuggestionEditRequest(BaseModel):
    edited_comment: str = Field(..., min_length=1, max_length=20_000)


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str
    citations: list[str] = Field(default_factory=list)
    timestamp: datetime
    session_id: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    citations: list[str] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None


class ChatCloseResponse(BaseModel):
    closed: bool


# ── Admin — config ─────────────────────────────────────────────────────────────

class KillSwitchStatusResponse(BaseModel):
    enabled: bool
    changed_at: datetime | None = None
    changed_by: str | None = None


class QdrantStatsResponse(BaseModel):
    documents_count: int   # distinct uploaded documents (source_type=document)
    tickets_count: int     # distinct resolved JSM tickets ingested (source_type=ticket)
    total_chunks: int      # raw Qdrant point count across both sources
    last_sync: datetime | None = None
    coverage_by_category: dict[str, int] = Field(default_factory=dict)


class DocumentSummary(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    uploaded_at: datetime | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


# ── Dashboard / Analytics ─────────────────────────────────────────────────────

class SystemHealthResponse(BaseModel):
    api_uptime_seconds: int
    gemini_latency_ms: float
    qdrant_query_ms: float
    ws_connections: int
    jsm_poll_last_run: datetime | None = None
    jsm_poll_next_run: datetime | None = None
    scheduler_running: bool
    polling_interval_minutes: int = 0


class TechnicianStats(BaseModel):
    queue_count: int
    low_conf_pending: int
    sla_breach_count: int


# ── Platform config ───────────────────────────────────────────────────────────

class PlatformConfigResponse(BaseModel):
    aura_enabled: bool
    itsm_provider: str
    confidence_threshold: float
    abstention_threshold: float
    conversation_idle_timeout_hours: int
    polling_interval_minutes: int
    ingestion_interval_hours: int
    collision_timeout_minutes: int
    assignment_timeout_minutes: int
    last_poll_timestamp: datetime | None = None
    last_sync_timestamp: datetime | None = None
    setup_complete: bool
    current_wizard_step: int
    kill_switch_changed_by: str | None = None
    kill_switch_changed_at: datetime | None = None
    accent_color: str | None = None
    company_name: str | None = None
    company_logo: str | None = None


class BrandingResponse(BaseModel):
    company_name: str | None = None
    company_logo: str | None = None
    accent_color: str | None = None
    itsm_provider: str = "jira"


class PlatformConfigUpdate(BaseModel):
    confidence_threshold: float | None = None
    abstention_threshold: float | None = None
    conversation_idle_timeout_hours: int | None = None
    polling_interval_minutes: int | None = None
    ingestion_interval_hours: int | None = None
    collision_timeout_minutes: int | None = None
    assignment_timeout_minutes: int | None = None


# ── Rollback ──────────────────────────────────────────────────────────────────

class RollbackResponse(BaseModel):
    success: bool
    details: str


# ── Frontend logging ──────────────────────────────────────────────────────────

class FrontendLogEntry(BaseModel):
    level: Literal["debug", "info", "warn", "error"] = "info"
    message: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] | None = None
    url: str | None = Field(None, max_length=500)
    stack: str | None = Field(None, max_length=4000)
    timestamp: datetime | None = None


# ── Master admin — tenant provisioning ────────────────────────────────────────
# master_admin's entire surface: create/list/suspend tenants and reset a
# tenant's admin credentials. Deliberately no ticket/audit data anywhere here.

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    admin_email: str = Field(..., min_length=3, max_length=255)
    admin_display_name: str = Field(..., min_length=1, max_length=200)
    # No itsm_provider here — the tenant's own admin picks Jira vs. Zendesk
    # (and enters its credentials) in the Setup Wizard's connection step,
    # not master_admin at provisioning time.


class TenantSummary(BaseModel):
    tenant_id: str
    name: str
    status: Literal["active", "suspended"]
    itsm_provider: str
    created_at: datetime
    admin_email: str | None = None
    user_count: int
    setup_complete: bool


class TenantCreateResponse(BaseModel):
    tenant: TenantSummary
    admin_email: str
    temporary_password: str


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["active", "suspended"] | None = None


class ResetTenantAdminResponse(BaseModel):
    admin_email: str
    temporary_password: str


# ── Generic ───────────────────────────────────────────────────────────────────

class OkResponse(BaseModel):
    ok: bool = True
