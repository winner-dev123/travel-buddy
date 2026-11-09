"""Report request/response models (mirror the contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

TargetTypeName = Literal["post", "comment", "user", "message", "group", "challenge", "media"]
ReasonName = Literal[
    "spam",
    "harassment",
    "hate",
    "sexual_content",
    "minor_safety",
    "violence",
    "self_harm",
    "scam",
    "privacy_violation",
    "impersonation",
    "illegal",
    "other",
]


class CreateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: TargetTypeName
    target_id: uuid.UUID
    reason: ReasonName
    details: str | None = Field(default=None, max_length=1000)
    also_block: StrictBool = False


class ReportReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    status: Literal["open", "in_review", "actioned", "dismissed"]
    created_at: datetime
