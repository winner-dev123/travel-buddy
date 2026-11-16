"""Pure provider rules (ADR-0036, docs/18 §2 and §5)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.providers.domain import (
    ApplicationFacts,
    Decision,
    DocumentKind,
    InquiryAction,
    InquiryStatus,
    MemberRole,
    ProviderKind,
    ProviderStatus,
    Side,
    average_response_seconds,
    bayesian_rating,
    can_deactivate,
    can_invite,
    can_remove,
    can_review,
    can_submit,
    decision_target,
    inquiry_transition,
    is_due_for_completion,
    is_expired,
    missing_for_submit,
)

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


@pytest.mark.req("PROV-003")
def test_application_lifecycle() -> None:
    assert can_submit(ProviderStatus.DRAFT)
    assert can_submit(ProviderStatus.CHANGES_REQUESTED)
    assert not can_submit(ProviderStatus.SUBMITTED)
    assert decision_target(ProviderStatus.SUBMITTED, Decision.APPROVE) is ProviderStatus.APPROVED
    assert (
        decision_target(ProviderStatus.SUBMITTED, Decision.REQUEST_CHANGES)
        is ProviderStatus.CHANGES_REQUESTED
    )
    assert decision_target(ProviderStatus.DRAFT, Decision.APPROVE) is None
    assert decision_target(ProviderStatus.APPROVED, Decision.REJECT) is None
    assert can_deactivate(ProviderStatus.SUSPENDED)
    assert not can_deactivate(ProviderStatus.REJECTED)


@pytest.mark.req("PROV-003")
def test_submission_gaps_depend_on_kind() -> None:
    facts = ApplicationFacts(
        kind=ProviderKind.COMPANY,
        has_display_name=True,
        has_base_destination=True,
        language_count=0,
        has_legal_name=False,
        document_kinds=frozenset({DocumentKind.IDENTITY}),
        terms_accepted=True,
    )
    assert missing_for_submit(facts) == [
        "languages",
        "legal_name",
        "document:business_registration",
    ]
    guide = ApplicationFacts(
        kind=ProviderKind.GUIDE,
        has_display_name=True,
        has_base_destination=True,
        language_count=1,
        has_legal_name=True,
        document_kinds=frozenset({DocumentKind.IDENTITY}),
        terms_accepted=True,
    )
    assert missing_for_submit(guide) == []


@pytest.mark.req("PROV-005")
@pytest.mark.parametrize(
    ("inviter", "role", "allowed"),
    [
        (MemberRole.OWNER, MemberRole.MANAGER, True),
        (MemberRole.OWNER, MemberRole.AGENT, True),
        (MemberRole.MANAGER, MemberRole.AGENT, True),
        (MemberRole.MANAGER, MemberRole.MANAGER, False),
        (MemberRole.AGENT, MemberRole.AGENT, False),
        (MemberRole.OWNER, MemberRole.OWNER, False),
    ],
)
def test_who_invites_whom(inviter: MemberRole, role: MemberRole, allowed: bool) -> None:
    assert can_invite(inviter, role) is allowed


@pytest.mark.req("PROV-005")
def test_removing_and_leaving() -> None:
    assert can_remove(MemberRole.AGENT, MemberRole.AGENT, is_self=True)
    assert not can_remove(MemberRole.OWNER, MemberRole.OWNER, is_self=True)
    assert can_remove(MemberRole.OWNER, MemberRole.MANAGER, is_self=False)
    assert can_remove(MemberRole.MANAGER, MemberRole.AGENT, is_self=False)
    assert not can_remove(MemberRole.MANAGER, MemberRole.MANAGER, is_self=False)
    assert not can_remove(MemberRole.AGENT, MemberRole.AGENT, is_self=False)


@pytest.mark.req("PROV-010")
@pytest.mark.parametrize(
    ("status", "action", "side", "expected"),
    [
        (InquiryStatus.OPEN, InquiryAction.ACCEPT, Side.PROVIDER, InquiryStatus.ACCEPTED),
        (InquiryStatus.OPEN, InquiryAction.ACCEPT, Side.TRAVELER, None),
        (InquiryStatus.OPEN, InquiryAction.DECLINE, Side.PROVIDER, InquiryStatus.DECLINED),
        (InquiryStatus.OPEN, InquiryAction.WITHDRAW, Side.TRAVELER, InquiryStatus.WITHDRAWN),
        (InquiryStatus.OPEN, InquiryAction.WITHDRAW, Side.PROVIDER, None),
        (InquiryStatus.OPEN, InquiryAction.CANCEL, Side.TRAVELER, None),
        (InquiryStatus.ACCEPTED, InquiryAction.COMPLETE, Side.PROVIDER, InquiryStatus.COMPLETED),
        (InquiryStatus.ACCEPTED, InquiryAction.COMPLETE, Side.TRAVELER, None),
        (InquiryStatus.ACCEPTED, InquiryAction.CANCEL, Side.TRAVELER, InquiryStatus.CANCELLED),
        (InquiryStatus.ACCEPTED, InquiryAction.CANCEL, Side.PROVIDER, InquiryStatus.CANCELLED),
        (InquiryStatus.DECLINED, InquiryAction.ACCEPT, Side.PROVIDER, None),
        (InquiryStatus.COMPLETED, InquiryAction.CANCEL, Side.PROVIDER, None),
    ],
)
def test_inquiry_transitions(
    status: InquiryStatus, action: InquiryAction, side: Side, expected: InquiryStatus | None
) -> None:
    assert inquiry_transition(status, action, side) is expected


@pytest.mark.req("PROV-010")
def test_expiry_and_completion_timing() -> None:
    created = NOW - timedelta(days=13)
    assert not is_expired(InquiryStatus.OPEN, created, None, NOW)
    assert is_expired(InquiryStatus.OPEN, NOW - timedelta(days=14), None, NOW)
    assert is_expired(InquiryStatus.OPEN, NOW, date(2026, 11, 15), NOW)
    assert not is_expired(InquiryStatus.ACCEPTED, NOW - timedelta(days=30), None, NOW)
    day = date(2026, 11, 15)
    assert is_due_for_completion(InquiryStatus.ACCEPTED, day, None, NOW, NOW)
    assert not is_due_for_completion(InquiryStatus.ACCEPTED, date(2026, 11, 16), None, NOW, NOW)
    assert is_due_for_completion(InquiryStatus.ACCEPTED, None, None, NOW - timedelta(days=30), NOW)
    assert not is_due_for_completion(InquiryStatus.OPEN, day, None, NOW, NOW)


@pytest.mark.req("PROV-011")
def test_review_window() -> None:
    assert can_review(InquiryStatus.COMPLETED, NOW - timedelta(days=60), NOW)
    assert not can_review(InquiryStatus.COMPLETED, NOW - timedelta(days=61), NOW)
    assert not can_review(InquiryStatus.ACCEPTED, NOW, NOW)


@pytest.mark.req("PROV-007")
def test_ranking_shrinks_small_samples() -> None:
    one_perfect = bayesian_rating(5, 1)
    many_great = bayesian_rating(48 * 40 // 10, 40)  # 40 reviews averaging 4.8
    assert many_great > one_perfect
    assert bayesian_rating(0, 0) == 4.0
    assert average_response_seconds(9000, 2) is None
    assert average_response_seconds(9000, 3) == 3000
