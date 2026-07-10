"""Provider-agnostic ticket/comment shapes shared by every ITSM client
(JSMClient, ZendeskClient, ...). `app/models/jsm.py` re-exports these as
`JSMTicket`/`JSMComment` for backwards compatibility with existing imports —
the names live here now since they're no longer Jira-specific.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ITSMComment(BaseModel):
    author: str
    author_account_id: str | None = None    # provider's id for the commenter (Jira accountId, Zendesk user id, ...)
    body: str
    created: datetime


class ITSMTicket(BaseModel):
    ticket_id: str                          # e.g. Jira "IT-1234" or Zendesk numeric ticket id as a string
    summary: str
    description: str | None = None
    comments: list[ITSMComment] = Field(default_factory=list)
    resolution_note: str | None = None
    category: str | None = None             # provider issue type / custom field
    priority: str = "Medium"
    status: str                             # provider-native status string
    created: datetime
    resolved: datetime | None = None
    assignee: str | None = None
    reporter_account_id: str | None = None  # provider's id for the reporter/requester
