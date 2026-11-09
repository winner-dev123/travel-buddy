"""Connection state machine and relationship rules (BL-2.04; CONN-001, CONN-002, CONN-004)."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.connections.domain import (
    Action,
    Actor,
    InvalidTransitionError,
    Relationship,
    RelationshipFacts,
    RequestStatus,
    ordered_pair,
    policy_allows,
    relationship,
    transition,
)

pytestmark = pytest.mark.req("CONN-001", "CONN-002")

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=10)

VALID = {
    (Action.ACCEPT, Actor.RECIPIENT): RequestStatus.ACCEPTED,
    (Action.DECLINE, Actor.RECIPIENT): RequestStatus.DECLINED,
    (Action.CANCEL, Actor.REQUESTER): RequestStatus.CANCELLED,
    (Action.EXPIRE, Actor.SYSTEM): RequestStatus.EXPIRED,
}


@pytest.mark.parametrize(("action", "actor"), list(itertools.product(Action, Actor)))
def test_every_transition_from_pending(action: Action, actor: Actor) -> None:
    expected = VALID.get((action, actor))
    if expected is None:
        with pytest.raises(InvalidTransitionError):
            transition(RequestStatus.PENDING, action, actor, expires_at=LATER, now=NOW)
    else:
        assert (
            transition(RequestStatus.PENDING, action, actor, expires_at=LATER, now=NOW) is expected
        )


@pytest.mark.parametrize(
    ("status", "action", "actor"),
    [
        (status, action, actor)
        for status in RequestStatus
        if status is not RequestStatus.PENDING
        for (action, actor) in VALID
    ],
)
def test_answered_requests_never_change_again(
    status: RequestStatus, action: Action, actor: Actor
) -> None:
    with pytest.raises(InvalidTransitionError):
        transition(status, action, actor, expires_at=LATER, now=NOW)


@pytest.mark.req("CONN-007")
def test_expired_requests_can_only_be_marked_expired() -> None:
    past = NOW - timedelta(seconds=1)
    for action, actor in [(Action.ACCEPT, Actor.RECIPIENT), (Action.CANCEL, Actor.REQUESTER)]:
        with pytest.raises(InvalidTransitionError, match="expired"):
            transition(RequestStatus.PENDING, action, actor, expires_at=past, now=NOW)
    expired = transition(
        RequestStatus.PENDING, Action.EXPIRE, Actor.SYSTEM, expires_at=past, now=NOW
    )
    assert expired is RequestStatus.EXPIRED


def _facts(**kw: bool) -> RelationshipFacts:
    values = {
        "blocked": False,
        "connected": False,
        "outgoing_pending": False,
        "incoming_pending": False,
        "declined_within_cooldown": False,
    }
    values.update(kw)
    return RelationshipFacts(**values)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (_facts(), Relationship.NONE),
        (_facts(declined_within_cooldown=True), Relationship.DECLINED),
        (
            _facts(incoming_pending=True, declined_within_cooldown=True),
            Relationship.REQUEST_RECEIVED,
        ),
        (_facts(outgoing_pending=True, incoming_pending=True), Relationship.REQUEST_PENDING),
        (_facts(connected=True, outgoing_pending=True), Relationship.CONNECTED),
        (_facts(blocked=True, connected=True), Relationship.BLOCKED),
    ],
)
def test_relationship_precedence(facts: RelationshipFacts, expected: Relationship) -> None:
    assert relationship(facts) is expected


@pytest.mark.req("CONN-004")
def test_recipient_policies() -> None:
    assert policy_allows("everyone", shared_context=False)
    assert policy_allows("shared_context", shared_context=True)
    assert not policy_allows("shared_context", shared_context=False)
    assert not policy_allows("nobody", shared_context=True)
    assert not policy_allows("unknown", shared_context=True)


def test_pairs_are_ordered_like_postgres_uuids() -> None:
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000001")
    assert ordered_pair(high, low) == (low, high)
    assert ordered_pair(low, high) == (low, high)
