"""User domain models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

UserRole = Literal["admin", "manager", "technician", "end_user"]


class UserBase(BaseModel):
    email: str
    display_name: str
    role: UserRole
    team_id: str | None = None
    jira_account_id: str | None = None  # real Jira accountId, for native assignee writes


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: UserRole | None = None
    team_id: str | None = None
    is_active: bool | None = None
    jira_account_id: str | None = None


class UserPublic(UserBase):
    user_id: str
    is_active: bool = True
    last_login: datetime | None = None
