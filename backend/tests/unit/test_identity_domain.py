from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.identity.domain import (
    RefreshMatch,
    RefreshOutcome,
    SessionTokenState,
    age_on,
    decide_refresh,
    derive_successor_token,
    device_name_from_user_agent,
    hash_token,
    is_age_eligible,
)
from app.modules.profiles.domain import default_display_name, handle_base, handle_with_suffix

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
LEEWAY = timedelta(seconds=30)


@pytest.mark.req("AUTH-008")
@pytest.mark.parametrize(
    ("birth", "today", "age"),
    [
        (date(2008, 11, 9), date(2026, 11, 9), 18),  # 18th birthday today
        (date(2008, 11, 10), date(2026, 11, 9), 17),  # tomorrow
        (date(2008, 2, 29), date(2026, 2, 28), 17),  # leap-day birthday not yet reached
        (date(2008, 2, 29), date(2026, 3, 1), 18),
    ],
)
def test_age_on(birth: date, today: date, age: int) -> None:
    assert age_on(birth, today) == age
    assert is_age_eligible(birth, today, 18) is (age >= 18)


def test_birth_date_in_future_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        age_on(date(2030, 1, 1), date(2026, 1, 1))


def _state(
    *,
    revoked: bool = False,
    rotated_ago: timedelta | None = None,
    expires_in: timedelta = timedelta(days=1),
) -> SessionTokenState:
    return SessionTokenState(
        revoked=revoked,
        expires_at=NOW + expires_in,
        rotated_at=NOW - rotated_ago if rotated_ago is not None else None,
    )


@pytest.mark.req("AUTH-007")
@pytest.mark.parametrize(
    ("match", "state", "outcome"),
    [
        (RefreshMatch.CURRENT, _state(), RefreshOutcome.ROTATE),
        (RefreshMatch.CURRENT, _state(expires_in=timedelta(0)), RefreshOutcome.EXPIRED),
        (RefreshMatch.CURRENT, _state(revoked=True), RefreshOutcome.REVOKED),
        (
            RefreshMatch.PREVIOUS,
            _state(rotated_ago=timedelta(seconds=30)),
            RefreshOutcome.REPLAY_SUCCESSOR,
        ),
        (
            RefreshMatch.PREVIOUS,
            _state(rotated_ago=timedelta(seconds=31)),
            RefreshOutcome.REUSE_DETECTED,
        ),
        (RefreshMatch.PREVIOUS, _state(rotated_ago=None), RefreshOutcome.REUSE_DETECTED),
        (
            RefreshMatch.PREVIOUS,
            _state(revoked=True, rotated_ago=timedelta(0)),
            RefreshOutcome.REVOKED,
        ),
        (
            RefreshMatch.RETIRED,
            _state(rotated_ago=timedelta(seconds=1)),
            RefreshOutcome.REUSE_DETECTED,
        ),
        (RefreshMatch.NONE, None, RefreshOutcome.INVALID),
    ],
)
def test_decide_refresh(
    match: RefreshMatch, state: SessionTokenState | None, outcome: RefreshOutcome
) -> None:
    assert decide_refresh(match, state, now=NOW, leeway=LEEWAY) is outcome


def test_successor_derivation_is_deterministic_and_keyed() -> None:
    raw = "refresh-token-value-0123456789abcdef"
    first = derive_successor_token(raw, b"k" * 32)
    assert first == derive_successor_token(raw, b"k" * 32)
    assert first != derive_successor_token(raw, b"j" * 32)
    assert first != raw
    assert len(first) >= 32
    assert hash_token(first) != hash_token(raw)


@pytest.mark.parametrize(
    ("ua", "label"),
    [
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit Chrome/130.0 Safari/537.36",
            "Chrome on macOS",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit Chrome/130.0 Safari/537.36 Edg/130.0",
            "Edge on Windows",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "Version/18.0 Mobile Safari/604.1",
            "Safari on iOS",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
            "Firefox on Linux",
        ),
        ("curl/8.0", None),
        (None, None),
    ],
)
def test_device_name_from_user_agent(ua: str | None, label: str | None) -> None:
    assert device_name_from_user_agent(ua) == label


@pytest.mark.req("PROF-005")
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Ana Souza", "ana.souza"),
        ("José  Álvarez", "jose.alvarez"),
        ("李", "traveler"),  # nothing usable after ASCII folding
        (None, "traveler"),
        ("x" * 60, "x" * 24),
    ],
)
def test_handle_base(name: str | None, expected: str) -> None:
    assert handle_base(name) == expected


def test_handle_with_suffix_validates() -> None:
    assert handle_with_suffix("ana.souza", 1234) == "ana.souza1234"
    with pytest.raises(ValueError, match="non-negative"):
        handle_with_suffix("ana", -1)


def test_default_display_name_never_uses_email() -> None:
    assert default_display_name("  Ana   Souza ") == "Ana Souza"
    assert default_display_name(None) == "Traveler"
    assert len(default_display_name("n" * 80)) == 50
