"""BL-1.04 end-to-end: profile PATCH, onboarding, preferences, privacy and consents.

Every successful response is validated against the normative OpenAPI contract.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_identity_flows import TERMS, _auth, _id_token, _register

pytestmark = pytest.mark.integration


def _signed_in(live: LiveApp, name: str = "Ana Souza") -> tuple[str, str]:
    response = _register(live, _id_token(live, name=name))
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body["tokens"]["access_token"]), str(body["user"]["account"]["id"])


def _events(live: LiveApp, user_id: str, event_type: str) -> int:
    count = db_scalar(
        live.db_url,
        "SELECT count(*) FROM outbox_events WHERE aggregate_id = :u AND event_type = :t",
        u=uuid.UUID(user_id),
        t=event_type,
    )
    assert isinstance(count, int)
    return count


def _problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "Problem")
    assert body["code"] == code
    return body


# ─────────────────────────────────── profile ───────────────────────────────────


@pytest.mark.req("PROF-001", "PROF-003", "PROF-004")
def test_update_profile_returns_me_and_emits_event(live_app: LiveApp) -> None:
    token, user_id = _signed_in(live_app)
    handle = f"ana_{uuid.uuid4().hex[:8]}"
    response = live_app.client.patch(
        "/v1/users/me",
        headers=_auth(token),
        json={
            "handle": handle,
            "display_name": "  Ana   Souza​ ",
            "bio": "Coffee, trains and night markets.\r\n\r\n\r\nAlways packing light.",
            "home_country_code": "BR",
            "home_region": "  São Paulo ",
            "travel_styles": ["food", "culture", "food"],
            "interests": ["Street food", "street  food", "Museums"],
            "languages_spoken": ["pt-BR", "en"],
            "account_visibility": "private",
        },
    )
    assert response.status_code == 200, response.text
    me = response.json()
    assert_matches_contract(me, "Me")
    profile = me["profile"]
    assert profile["handle"] == handle
    assert profile["display_name"] == "Ana Souza"
    assert profile["bio"] == "Coffee, trains and night markets.\n\nAlways packing light."
    assert profile["home_region"] == "São Paulo"
    assert profile["travel_styles"] == ["food", "culture"]
    assert profile["interests"] == ["Street food", "Museums"]
    assert profile["account_visibility"] == "private"
    assert _events(live_app, user_id, "profile.updated") == 1


def test_clearing_optional_fields_with_null(live_app: LiveApp) -> None:
    token, _ = _signed_in(live_app)
    live_app.client.patch("/v1/users/me", headers=_auth(token), json={"bio": "Hello"})
    response = live_app.client.patch(
        "/v1/users/me", headers=_auth(token), json={"bio": None, "home_region": "   "}
    )
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["bio"] is None
    assert response.json()["profile"]["home_region"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"display_name": None},
        {"handle": "Has Spaces"},
        {"handle": "ab"},
        {"travel_styles": ["sightseeing"]},
        {"display_name": "​​"},
        {"email": "x@example.com"},
    ],
)
def test_invalid_profile_patches_are_rejected(live_app: LiveApp, body: dict[str, Any]) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.patch("/v1/users/me", headers=_auth(token), json=body)
    _problem(response, 422, "validation_failed")


@pytest.mark.security
@pytest.mark.parametrize("handle", ["admin", "a.d.m.i.n", "travel_buddy_support", "support"])
def test_reserved_handles_are_rejected(live_app: LiveApp, handle: str) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.patch("/v1/users/me", headers=_auth(token), json={"handle": handle})
    body = _problem(response, 422, "validation_failed")
    assert body["errors"][0]["code"] == "reserved"


@pytest.mark.req("PROF-003")
def test_handles_are_unique_case_insensitively(live_app: LiveApp) -> None:
    first, _ = _signed_in(live_app)
    second, _ = _signed_in(live_app, name="Bo Lee")
    handle = f"taken_{uuid.uuid4().hex[:8]}"
    assert (
        live_app.client.patch(
            "/v1/users/me", headers=_auth(first), json={"handle": handle}
        ).status_code
        == 200
    )
    response = live_app.client.patch("/v1/users/me", headers=_auth(second), json={"handle": handle})
    _problem(response, 409, "conflict")


@pytest.mark.req("PROF-003")
def test_handle_can_change_once_per_30_days(live_app: LiveApp) -> None:
    token, user_id = _signed_in(live_app)
    first = f"first_{uuid.uuid4().hex[:8]}"
    second = f"second_{uuid.uuid4().hex[:8]}"
    # The generated handle can be replaced at once (onboarding).
    assert (
        live_app.client.patch("/v1/users/me", headers=_auth(token), json={"handle": first})
    ).status_code == 200
    # Re-sending the current handle is a no-op, not a change.
    assert (
        live_app.client.patch("/v1/users/me", headers=_auth(token), json={"handle": first})
    ).status_code == 200
    too_soon = live_app.client.patch("/v1/users/me", headers=_auth(token), json={"handle": second})
    body = _problem(too_soon, 422, "validation_failed")
    assert body["errors"][0]["code"] == "change_too_soon"
    assert "next_change_at" in body

    db_scalar(
        live_app.db_url,
        "UPDATE user_profiles SET handle_changed_at = now() - interval '31 days' "
        "WHERE user_id = :u RETURNING 1",
        u=uuid.UUID(user_id),
    )
    later = live_app.client.patch("/v1/users/me", headers=_auth(token), json={"handle": second})
    assert later.status_code == 200, later.text
    assert later.json()["profile"]["handle"] == second


def test_avatar_cannot_reference_unknown_media(live_app: LiveApp) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.patch(
        "/v1/users/me", headers=_auth(token), json={"avatar_media_id": str(uuid.uuid4())}
    )
    body = _problem(response, 422, "validation_failed")
    assert body["errors"][0]["field"] == "/avatar_media_id"


def test_profile_patch_requires_authentication(live_app: LiveApp) -> None:
    response = live_app.client.patch("/v1/users/me", json={"display_name": "X"})
    _problem(response, 401, "unauthenticated")


# ─────────────────────────────────── onboarding ───────────────────────────────────


@pytest.mark.req("PROF-001", "PROF-002")
def test_complete_onboarding_is_idempotent(live_app: LiveApp) -> None:
    token, user_id = _signed_in(live_app)
    for _ in range(2):
        response = live_app.client.post("/v1/users/me/onboarding/complete", headers=_auth(token))
        assert response.status_code == 200, response.text
        assert_matches_contract(response.json(), "Me")
        assert response.json()["onboarding_completed"] is True
    assert _events(live_app, user_id, "user.onboarding_completed") == 1


# ─────────────────────────────────── preferences ───────────────────────────────────


@pytest.mark.req("PROF-006", "I18N-002")
def test_preferences_round_trip_and_notification_merge(live_app: LiveApp) -> None:
    token, _ = _signed_in(live_app)
    initial = live_app.client.get("/v1/users/me/preferences", headers=_auth(token))
    assert initial.status_code == 200
    assert_matches_contract(initial.json(), "Preferences")

    first = live_app.client.patch(
        "/v1/users/me/preferences",
        headers=_auth(token),
        json={
            "ui_locale": "es",
            "content_languages": ["es", "en", "es"],
            "time_zone": "America/Sao_Paulo",
            "currency_code": "BRL",
            "distance_unit": "mi",
            "auto_translate": True,
            "notification_settings": {"new_message": {"push": False, "email": False}},
        },
    )
    assert first.status_code == 200, first.text
    assert_matches_contract(first.json(), "Preferences")
    second = live_app.client.patch(
        "/v1/users/me/preferences",
        headers=_auth(token),
        json={"notification_settings": {"new_message": {"push": True}, "post_comment": {}}},
    )
    prefs = second.json()
    assert_matches_contract(prefs, "Preferences")
    assert prefs["ui_locale"] == "es"
    assert prefs["content_languages"] == ["es", "en"]
    assert prefs["distance_unit"] == "mi"
    assert prefs["notification_settings"]["new_message"] == {"push": True, "email": False}


@pytest.mark.parametrize(
    "body",
    [
        {"ui_locale": "ja"},
        {"time_zone": "Mars/Olympus_Mons"},
        {"currency_code": "brl"},
        {"notification_settings": {"not_a_type": {"push": True}}},
        {"notification_settings": {"new_message": {"sms": True}}},
        {"notification_settings": {"new_message": {"push": None}}},
        {"auto_translate": "yes"},
    ],
)
def test_invalid_preferences_are_rejected(live_app: LiveApp, body: dict[str, Any]) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.patch("/v1/users/me/preferences", headers=_auth(token), json=body)
    _problem(response, 422, "validation_failed")


def test_registration_locale_is_negotiated_to_a_supported_ui_locale(live_app: LiveApp) -> None:
    response = _register(live_app, _id_token(live_app), locale="pt-PT")
    assert response.status_code == 201, response.text
    assert response.json()["user"]["preferences"]["ui_locale"] == "pt-BR"
    assert response.json()["user"]["account"]["primary_locale"] == "pt-PT"


# ─────────────────────────────────── privacy & consents ───────────────────────────────────


@pytest.mark.req("PROF-007", "DISC-001")
@pytest.mark.security
def test_discovery_requires_consent_and_withdrawal_turns_it_off(live_app: LiveApp) -> None:
    token, user_id = _signed_in(live_app)
    denied = live_app.client.patch(
        "/v1/users/me/privacy", headers=_auth(token), json={"discovery_enabled": True}
    )
    body = _problem(denied, 403, "consent_required")
    assert body["consent_type"] == "traveler_discovery"

    granted = live_app.client.post(
        "/v1/users/me/consents",
        headers=_auth(token),
        json={
            "consent_type": "traveler_discovery",
            "version": "2026-11-01",
            "granted": True,
            "source": "prompt",
        },
    )
    assert granted.status_code == 201, granted.text
    assert_matches_contract(granted.json(), "ConsentRecord")

    enabled = live_app.client.patch(
        "/v1/users/me/privacy",
        headers=_auth(token),
        json={"discovery_enabled": True, "discovery_granularity": "neighborhood"},
    )
    assert enabled.status_code == 200, enabled.text
    settings = enabled.json()
    assert_matches_contract(settings, "PrivacySettings")
    assert settings["discovery_enabled"] is True
    assert settings["discovery_consent"]["version"] == "2026-11-01"

    withdrawn = live_app.client.post(
        "/v1/users/me/consents",
        headers=_auth(token),
        json={
            "consent_type": "traveler_discovery",
            "version": "2026-11-01",
            "granted": False,
            "source": "settings",
        },
    )
    assert withdrawn.status_code == 201
    after = live_app.client.get("/v1/users/me/privacy", headers=_auth(token)).json()
    assert after["discovery_enabled"] is False
    assert after["discovery_consent"] is None
    assert _events(live_app, user_id, "discovery.disabled") == 1


@pytest.mark.req("PROF-008")
def test_search_indexing_toggle_is_recorded_as_consent(live_app: LiveApp) -> None:
    token, user_id = _signed_in(live_app)
    on = live_app.client.patch(
        "/v1/users/me/privacy", headers=_auth(token), json={"search_engine_indexing": True}
    )
    assert on.status_code == 200, on.text
    assert on.json()["search_engine_indexing"] is True
    # Unchanged value: no duplicate consent record.
    live_app.client.patch(
        "/v1/users/me/privacy", headers=_auth(token), json={"search_engine_indexing": True}
    )
    consents = live_app.client.get("/v1/users/me/consents", headers=_auth(token)).json()
    by_type = {c["consent_type"]: c for c in consents["data"]}
    assert by_type["search_indexing"]["granted"] is True
    assert by_type["terms"]["version"] == TERMS
    records = db_scalar(
        live_app.db_url,
        "SELECT count(*) FROM consent_records "
        "WHERE user_id = :u AND consent_type = 'search_indexing'",
        u=uuid.UUID(user_id),
    )
    assert records == 1
    assert _events(live_app, user_id, "privacy.updated") == 1

    # Withdrawing through the consent endpoint switches indexing off (same setting).
    live_app.client.post(
        "/v1/users/me/consents",
        headers=_auth(token),
        json={
            "consent_type": "search_indexing",
            "version": TERMS,
            "granted": False,
            "source": "settings",
        },
    )
    privacy = live_app.client.get("/v1/users/me/privacy", headers=_auth(token)).json()
    assert privacy["search_engine_indexing"] is False


def test_consent_list_matches_contract(live_app: LiveApp) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.get("/v1/users/me/consents", headers=_auth(token))
    assert response.status_code == 200
    for record in response.json()["data"]:
        assert_matches_contract(record, "ConsentRecord")
    assert {c["consent_type"] for c in response.json()["data"]} == {"terms", "privacy_policy"}


@pytest.mark.req("AUTH-009")
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"consent_type": "terms", "version": TERMS, "granted": False}, "cannot_withdraw"),
        (
            {"consent_type": "privacy_policy", "version": "2020-01-01", "granted": True},
            "outdated_version",
        ),
    ],
)
def test_legal_consents_cannot_be_withdrawn_or_downgraded(
    live_app: LiveApp, body: dict[str, Any], code: str
) -> None:
    token, _ = _signed_in(live_app)
    response = live_app.client.post(
        "/v1/users/me/consents", headers=_auth(token), json={**body, "source": "settings"}
    )
    problem = _problem(response, 422, "validation_failed")
    assert problem["errors"][0]["code"] == code
