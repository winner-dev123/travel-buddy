"""Connection API shapes (contract ``CreateConnectionRequestRequest``, ``ConnectionRequest``,
``Connection``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.profiles.schemas import UserSummary

Context = Literal["discovery", "group", "profile", "post"]
Status = Literal["pending", "accepted", "declined", "cancelled", "expired"]


class CreateConnectionRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    context: Context
    context_ref_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=140)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class ConnectionRequestOut(_Response):
    id: uuid.UUID
    requester: UserSummary
    recipient: UserSummary
    status: Status
    context: Context
    note: str | None
    created_at: datetime
    responded_at: datetime | None
    expires_at: datetime


class ConnectionOut(_Response):
    user: UserSummary
    connected_at: datetime
    conversation_id: uuid.UUID | None = None  # direct messages arrive in Phase 3
