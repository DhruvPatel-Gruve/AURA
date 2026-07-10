"""Audit and rollback record models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditStep(BaseModel):
    node_name: str
    timestamp: str                          # ISO-8601 UTC
    decision: str                           # Human-readable outcome
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEntry(BaseModel):
    entry_id: str                           # UUID
    tenant_id: str
    ticket_id: str
    action_taken: str
    priority: str | None = None
    category: str | None = None
    auto_comment_enabled: bool | None = None
    confidence_score: float | None = None
    abstained: bool = False
    jsm_comment_id: str | None = None
    rollback_ref: str | None = None
    audit_steps: list[AuditStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RollbackRecord(BaseModel):
    action_id: str                          # UUID
    ticket_id: str
    action_type: str                        # "comment_posted" | etc.
    rollback_call: dict[str, Any]           # { method, url, body }
    actor: str                              # user_id or "AURA_AGENT"
    created_at: datetime
    rolled_back_at: datetime | None = None
    rolled_back_by: str | None = None
