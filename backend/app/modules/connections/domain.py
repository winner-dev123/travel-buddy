"""Connection request state machine and derived relationship state (pure; CONN-001/002/006/007).

A request moves ``pending → accepted | declined | cancelled | expired`` and never back. Only the
recipient accepts or declines, only the requester cancels, and nothing ever connects two people
without an explicit accept (CONN-002).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

REQUEST_TTL = timedelta(days=30)  # CONN-007
DECLINE_COOLDOWN = timedelta(days=30)  # CONN-006
NEW_ACCOUNT_AGE = timedelta(days=7)  # CONN-005
NEW_ACCOUNT_DAILY_LIMIT = 5
NOTE_MAX = 140


class RequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Action(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"
    EXPIRE = "expire"


class Actor(StrEnum):
    REQUESTER = "requester"
    RECIPIENT = "recipient"
    SYSTEM = "system"


_TRANSITIONS: dict[tuple[Action, Actor], RequestStatus] = {
    (Action.ACCEPT, Actor.RECIPIENT): RequestStatus.ACCEPTED,
    (Action.DECLINE, Actor.RECIPIENT): RequestStatus.DECLINED,
    (Action.CANCEL, Actor.REQUESTER): RequestStatus.CANCELLED,
    (Action.EXPIRE, Actor.SYSTEM): RequestStatus.EXPIRED,
}


class InvalidTransitionError(Exception):
    pass


def transition(
    status: RequestStatus, action: Action, actor: Actor, *, expires_at: datetime, now: datetime
) -> RequestStatus:
    """The next status, or ``InvalidTransitionError`` (wrong state, wrong party, or expired)."""
    if status is not RequestStatus.PENDING:
        raise InvalidTransitionError(f"request is {status}")
    if action is not Action.EXPIRE and now >= expires_at:
        raise InvalidTransitionError("request expired")
    target = _TRANSITIONS.get((action, actor))
    if target is None:
        raise InvalidTransitionError(f"{actor} cannot {action}")
    return target


class Relationship(StrEnum):
    NONE = "none"
    REQUEST_PENDING = "request_pending"
    REQUEST_RECEIVED = "request_received"
    CONNECTED = "connected"
    DECLINED = "declined"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RelationshipFacts:
    blocked: bool
    connected: bool
    outgoing_pending: bool
    incoming_pending: bool
    declined_within_cooldown: bool


def relationship(facts: RelationshipFacts) -> Relationship:
    """Viewer's view of another user, by precedence (docs/04 §6)."""
    if facts.blocked:
        return Relationship.BLOCKED
    if facts.connected:
        return Relationship.CONNECTED
    if facts.outgoing_pending:
        return Relationship.REQUEST_PENDING
    if facts.incoming_pending:
        return Relationship.REQUEST_RECEIVED
    if facts.declined_within_cooldown:
        return Relationship.DECLINED
    return Relationship.NONE


def policy_allows(policy: str, *, shared_context: bool) -> bool:
    """The recipient's ``connection_requests_from`` setting (CONN-004)."""
    if policy == "everyone":
        return True
    if policy == "shared_context":
        return shared_context
    return False


def ordered_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Canonical (low, high) ordering for ``user_connections`` (same order as PostgreSQL's uuid)."""
    return (a, b) if a.int < b.int else (b, a)
