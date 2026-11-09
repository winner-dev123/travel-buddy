"""Notification API shapes (contract ``Notification``, ``NotificationPage``,
``MarkNotificationsReadRequest``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.pagination import PageInfo
from app.modules.profiles.schemas import UserSummary


class NotificationOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: str
    actor: UserSummary | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    title: str
    body: str
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    data: list[NotificationOut]
    page: PageInfo


class UnreadCount(BaseModel):
    count: int


class MarkNotificationsReadRequest(BaseModel):
    """Either ``{"ids": [...]}`` (1-100) or ``{"all": true}``."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=100)
    all: Literal[True] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.ids is None) == (self.all is None):
            raise ValueError("send either 'ids' or 'all': true")
        return self
