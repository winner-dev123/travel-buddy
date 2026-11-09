"""User-selected locations (docs/04 section 4). Private to the location module.

Destinations a user chose: never a device position. Device coordinates are request-scoped only
(LOC-003) and are not stored anywhere.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class SelectionKind(StrEnum):
    BROWSE = "browse"
    UPCOMING = "upcoming"
    SAVED = "saved"


class UserSelectedLocation(Base):
    __tablename__ = "user_selected_locations"
    __table_args__ = (
        enum_check("kind", SelectionKind, "kind_enum"),
        Index(
            "uq_user_selected_locations__one_browse",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'browse'"),
        ),
        Index(
            "uq_user_selected_locations__user_destination_kind",
            "user_id",
            "destination_id",
            "kind",
            unique=True,
        ),
        Index("ix_user_selected_locations__destination", "destination_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    share_for_discovery: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
