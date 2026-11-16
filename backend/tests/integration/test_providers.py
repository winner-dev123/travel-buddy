"""Guides and travel companies end to end (ADR-0036, docs/18; PROV-001..015)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.providers import service as providers_service
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _report, _staff
from tests.integration.test_posts import _destination, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

RIO = "brazil/rio-de-janeiro"


def _idem(token: str) -> dict[str, str]:
    return {**_auth(token), "Idempotency-Key": str(uuid.uuid4())}


def _handle(live: LiveApp, user_id: str) -> str:
    return str(
        db_scalar(
            live.db_url, "SELECT handle FROM user_profiles WHERE user_id = :u", u=uuid.UUID(user_id)
        )
    )


def _create(live: LiveApp, token: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "kind": "guide",
        "display_name": "Carioca Walks",
        "country_code": "BR",
        "base_destination_id": _destination(live, RIO),
        "legal_name": "Ana Souza",
        "tagline": "Hidden Rio on foot",
        "languages": ["pt-BR", "en"],
        "specialties": ["city_tours", "history_culture"],
        **overrides,
    }
    return live.client.post("/v1/providers", headers=_idem(token), json=body)


def _draft(live: LiveApp, token: str, **overrides: Any) -> dict[str, Any]:
    created = _create(live, token, **overrides)
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _document(live: LiveApp, token: str, owner_id: str, provider_id: str, kind: str) -> Any:
    media_id = db_scalar(
        live.db_url,
        "INSERT INTO media_assets (id, owner_id, purpose, status, mime_type, bytes, sha256, "
        "quarantine_key) VALUES (gen_random_uuid(), :o, 'provider_document', 'scanning', "
        "'image/jpeg', 10, 'x', 'q') RETURNING id",
        o=uuid.UUID(owner_id),
    )
    return live.client.post(
        f"/v1/providers/{provider_id}/documents",
        headers=_auth(token),
        json={"kind": kind, "media_id": str(media_id), "number": "27.123456.10.0001-9"},
    )


def _submit(live: LiveApp, token: str, provider: dict[str, Any]) -> Any:
    return live.client.post(
        f"/v1/providers/{provider['id']}/submit",
        headers=_auth(token),
        json={"terms_version": provider["terms_version"]},
    )


def _decide(
    live: LiveApp, staff: str, provider_id: str, decision: str, note: str | None = None
) -> Any:
    body: dict[str, Any] = {"decision": decision}
    if note:
        body["note"] = note
    return live.client.post(
        f"/v1/admin/providers/{provider_id}/decision", headers=_admin(staff), json=body
    )


def _approved(live: LiveApp, **overrides: Any) -> tuple[str, str, dict[str, Any]]:
    """An approved provider: (owner token, owner id, workspace)."""
    token, user_id = _user(live)
    provider = _draft(live, token, **overrides)
    assert _document(live, token, user_id, provider["id"], "identity").status_code == 201
    if provider["kind"] == "company":
        made = _document(live, token, user_id, provider["id"], "business_registration")
        assert made.status_code == 201
    assert _submit(live, token, provider).status_code == 200
    staff, _ = _staff(live)
    decided = _decide(live, staff, provider["id"], "approve")
    assert decided.status_code == 200, decided.text
    workspace = live.client.get(f"/v1/providers/{provider['id']}/workspace", headers=_auth(token))
    return token, user_id, workspace.json()


def _offering(live: LiveApp, token: str, provider_id: str, **overrides: Any) -> dict[str, Any]:
    body = {
        "kind": "tour",
        "title": "Santa Teresa and Lapa at sunset",
        "destination_id": _destination(live, RIO),
        "duration_minutes": 180,
        "price_from_minor": 15000,
        "currency": "BRL",
        "price_unit": "per_person",
        **overrides,
    }
    created = live.client.post(
        f"/v1/providers/{provider_id}/offerings", headers=_auth(token), json=body
    )
    assert created.status_code == 201, created.text
    data: dict[str, Any] = created.json()
    return data


def _inquiry(live: LiveApp, token: str, provider_id: str, **overrides: Any) -> Any:
    body = {
        "start_date": (live.clock.now().date() + timedelta(days=10)).isoformat(),
        "party_size": 2,
        "message": "Hi! Could you show us Santa Teresa next week?",
        **overrides,
    }
    return live.client.post(
        f"/v1/providers/{provider_id}/inquiries", headers=_idem(token), json=body
    )


def _say(live: LiveApp, token: str, conversation: str, body: str = "Hello!") -> Any:
    return live.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers=_idem(token),
        json={"client_message_id": str(uuid.uuid4()), "body": body},
    )


def _act(live: LiveApp, token: str, inquiry_id: str, action: str, **body: Any) -> Any:
    return live.client.post(
        f"/v1/provider-inquiries/{inquiry_id}/{action}",
        headers=_auth(token),
        json=body or None,
    )


def _run(live: LiveApp, work: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(live.db_url)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session, session.begin():
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(go())


# ─────────────────────────────── applying and verification ───────────────────────────────


@pytest.mark.req("PROV-001", "PROV-002", "PROV-003", "PROV-004", "PROV-013", "PROV-014")
def test_apply_submit_and_staff_approval(app: LiveApp) -> None:  # noqa: F811
    unverified, _ = _user(app, verified=False)
    _problem(_create(app, unverified), 403, "email_unverified")

    token, user_id = _user(app)
    provider = _draft(app, token)
    assert_matches_contract(provider, "ProviderWorkspace")
    assert provider["status"] == "draft"
    assert provider["membership"] == {"role": "owner", "status": "active"}
    assert "document:identity" in provider["missing_for_submit"]
    _problem(_create(app, token, display_name="Another me"), 409, "guide_profile_exists")

    # Drafts are invisible to everyone but the team.
    stranger, _ = _user(app)
    _problem(
        app.client.get(f"/v1/providers/{provider['id']}", headers=_auth(stranger)), 404, "not_found"
    )
    assert (
        app.client.get(f"/v1/providers/{provider['id']}", headers=_auth(token)).status_code == 200
    )

    incomplete = _submit(app, token, provider)
    assert _problem(incomplete, 422, "provider_incomplete")["missing"] == ["document:identity"]
    document = _document(app, token, user_id, provider["id"], "identity")
    assert document.status_code == 201, document.text
    assert_matches_contract(document.json(), "ProviderDocument")
    assert "url" not in document.json()
    _problem(
        app.client.post(
            f"/v1/providers/{provider['id']}/submit",
            headers=_auth(token),
            json={"terms_version": "1999-01-01"},
        ),
        422,
        "validation_failed",
    )
    submitted = _submit(app, token, provider)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM consent_records WHERE user_id = :u "
            "AND consent_type = 'provider_terms'",
            u=uuid.UUID(user_id),
        )
        == 1
    )

    # Staff: queue, full application, signed document link (no storage here → 410), decision.
    support, _ = _staff(app, "support")
    _problem(app.client.get("/v1/admin/providers", headers=_admin(support)), 403, "forbidden")
    staff, staff_id = _staff(app)
    queue = app.client.get(
        "/v1/admin/providers", params={"status": "submitted"}, headers=_admin(staff)
    )
    assert queue.status_code == 200, queue.text
    assert_matches_contract(queue.json(), "AdminProviderPage")
    assert provider["id"] in [p["id"] for p in queue.json()["data"]]
    _problem(
        app.client.get(f"/v1/admin/providers/{provider['id']}", headers=_admin(staff, None)),
        400,
        "justification_required",
    )
    detail = app.client.get(f"/v1/admin/providers/{provider['id']}", headers=_admin(staff))
    assert detail.status_code == 200, detail.text
    assert_matches_contract(detail.json(), "AdminProvider")
    assert detail.json()["provider"]["legal_name"] == "Ana Souza"
    assert detail.headers["cache-control"] == "no-store"
    document_id = detail.json()["documents"][0]["id"]
    link = app.client.get(
        f"/v1/admin/providers/{provider['id']}/documents/{document_id}/file",
        headers=_admin(staff),
    )
    # The test photo never finishes processing, so there's no file to sign yet.
    assert link.status_code == 409, link.text

    changes = _decide(app, staff, provider["id"], "request_changes", "Please add your CADASTUR.")
    assert changes.status_code == 200, changes.text
    assert changes.json()["provider"]["status"] == "changes_requested"
    assert changes.json()["provider"]["review_note"] == "Please add your CADASTUR."
    assert _document(app, token, user_id, provider["id"], "tourism_registry").status_code == 201
    assert _submit(app, token, provider).status_code == 200
    approved = _decide(app, staff, provider["id"], "approve")
    assert approved.json()["provider"]["status"] == "approved"
    assert {d["status"] for d in approved.json()["documents"]} == {"accepted"}
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM audit_logs WHERE resource_id = :p AND action LIKE 'provider.%'",
            p=provider["id"],
        )
        == 3  # viewed, changes requested, approved
    )
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM notifications WHERE user_id = :u "
            "AND type = 'provider_application'",
            u=uuid.UUID(user_id),
        )
        == 2
    )

    # Public now, without private fields; verified fields locked.
    public = app.client.get(f"/v1/providers/{provider['id']}")
    assert public.status_code == 200, public.text
    assert_matches_contract(public.json(), "ProviderProfile")
    assert public.json()["verified_at"] is not None
    for private in ("legal_name", "registration_number", "review_note", "members"):
        assert private not in public.json()
    locked = app.client.patch(
        f"/v1/providers/{provider['id']}", headers=_auth(token), json={"legal_name": "Someone Else"}
    )
    assert _problem(locked, 409, "provider_field_locked")["fields"] == ["legal_name"]
    edited = app.client.patch(
        f"/v1/providers/{provider['id']}",
        headers={**_auth(token), "If-Match": f'"{approved.json()["provider"]["version"]}"'},
        json={"about": "Born and raised in Santa Teresa.", "years_experience": 8},
    )
    assert edited.status_code == 200, edited.text
    assert edited.headers["etag"] == f'"{edited.json()["version"]}"'
    assert staff_id  # used


@pytest.mark.req("PROV-007", "PROV-008")
def test_listing_by_area_language_and_specialty(app: LiveApp) -> None:  # noqa: F811
    _, _, guide = _approved(app)
    _, _, company = _approved(
        app,
        kind="company",
        display_name="Lisboa Transfers",
        base_destination_id=_destination(app, "portugal/lisbon"),
        country_code="PT",
        languages=["pt", "fr"],
        specialties=["transfers"],
    )
    traveler, _ = _user(app)

    def ids(**params: Any) -> list[str]:
        response = app.client.get("/v1/providers", headers=_auth(traveler), params=params)
        assert response.status_code == 200, response.text
        assert_matches_contract(response.json(), "ProviderPage")
        return [p["id"] for p in response.json()["data"]]

    copacabana = _destination(app, "brazil/rio-de-janeiro/copacabana")
    brazil = _destination(app, "brazil")
    # Other tests in this module add providers too, so check membership, not exact lists.
    lisbon = _destination(app, "portugal/lisbon")
    in_copacabana = ids(destination_id=copacabana)  # serves the city it is part of
    assert guide["id"] in in_copacabana
    assert company["id"] not in in_copacabana
    assert guide["id"] in ids(destination_id=brazil)  # a town inside the country
    in_lisbon = ids(destination_id=lisbon)
    assert company["id"] in in_lisbon
    assert guide["id"] not in in_lisbon
    assert set(ids()) >= {guide["id"], company["id"]}
    assert guide["id"] in ids(language="pt", destination_id=brazil)  # pt matches pt-BR
    assert company["id"] in ids(language="fr")
    assert guide["id"] not in ids(language="fr")
    transfers = ids(specialty="transfers")
    assert company["id"] in transfers
    assert guide["id"] not in transfers
    assert company["id"] not in ids(kind="guide", destination_id=lisbon)

    # Service areas widen the reach.
    owner = app.client.get(f"/v1/providers/{guide['id']}/workspace")
    assert owner.status_code == 401
    paris = _destination(app, "france/paris")
    assert guide["id"] not in ids(destination_id=paris)

    # Pagination is stable.
    first = app.client.get("/v1/providers", params={"limit": 1}).json()
    assert first["page"]["has_more"] is True
    second = app.client.get(
        "/v1/providers", params={"limit": 1, "cursor": first["page"]["next_cursor"]}
    ).json()
    assert first["data"][0]["id"] != second["data"][0]["id"]


@pytest.mark.req("PROV-002")
def test_service_areas_and_their_limit(app: LiveApp) -> None:  # noqa: F811
    token, _, guide = _approved(app)
    paris = _destination(app, "france/paris")
    updated = app.client.put(
        f"/v1/providers/{guide['id']}/service-areas",
        headers=_auth(token),
        json={"destination_ids": [paris]},
    )
    assert updated.status_code == 200, updated.text
    assert [a["id"] for a in updated.json()["service_areas"]] == [paris]
    listed = app.client.get("/v1/providers", params={"destination_id": paris}).json()
    assert guide["id"] in [p["id"] for p in listed["data"]]
    _problem(
        app.client.put(
            f"/v1/providers/{guide['id']}/service-areas",
            headers=_auth(token),
            json={"destination_ids": [str(uuid.uuid4())]},
        ),
        422,
        "validation_failed",
    )


@pytest.mark.req("PROV-006")
def test_offerings_publish_only_when_approved(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    draft = _draft(app, token)
    offering = _offering(app, token, draft["id"])
    assert_matches_contract(offering, "Offering")
    assert offering["price_from"] == {
        "amount_minor": 15000,
        "currency": "BRL",
        "unit": "per_person",
        "indicative": True,
    }
    _problem(
        app.client.post(f"/v1/provider-offerings/{offering['id']}/publish", headers=_auth(token)),
        409,
        "provider_not_approved",
    )

    owner, _, approved = _approved(app, display_name="Rio by Bike")
    live = _offering(app, owner, approved["id"], title="Bike the lagoon")
    published = app.client.post(
        f"/v1/provider-offerings/{live['id']}/publish", headers=_auth(owner)
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    hidden = _offering(app, owner, approved["id"], title="A draft idea")
    public = app.client.get(f"/v1/providers/{approved['id']}/offerings").json()
    assert [o["id"] for o in public["data"]] == [live["id"]]
    mine = app.client.get(
        f"/v1/providers/{approved['id']}/offerings", params={"status": "all"}, headers=_auth(owner)
    ).json()
    assert {o["id"] for o in mine["data"]} == {live["id"], hidden["id"]}
    _problem(app.client.get(f"/v1/provider-offerings/{hidden['id']}"), 404, "not_found")
    assert app.client.get(f"/v1/provider-offerings/{live['id']}").status_code == 200
    assert user_id


# ─────────────────────────────── requests, chat and reviews ───────────────────────────────


@pytest.mark.req("PROV-009", "PROV-010", "PROV-011", "PROV-014")
def test_request_chat_accept_complete_and_review(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id, provider = _approved(app)
    offering = _offering(app, owner, provider["id"])
    app.client.post(f"/v1/provider-offerings/{offering['id']}/publish", headers=_auth(owner))
    traveler, traveler_id = _user(app)

    _problem(_inquiry(app, owner, provider["id"]), 403, "forbidden")  # own team
    _problem(
        _inquiry(
            app,
            traveler,
            provider["id"],
            start_date=(app.clock.now().date() - timedelta(days=1)).isoformat(),
        ),
        422,
        "validation_failed",
    )
    sent = _inquiry(app, traveler, provider["id"], offering_id=offering["id"])
    assert sent.status_code == 201, sent.text
    inquiry = sent.json()
    assert_matches_contract(inquiry, "Inquiry")
    assert inquiry["status"] == "open"
    assert inquiry["viewer_side"] == "traveler"
    assert inquiry["offering"]["id"] == offering["id"]
    _problem(_inquiry(app, traveler, provider["id"]), 409, "inquiry_already_open")
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM notifications WHERE user_id = :u AND type = 'provider_inquiry'",
            u=uuid.UUID(owner_id),
        )
        == 1
    )

    # The provider chat works without a connection, both ways.
    conversation = inquiry["conversation_id"]
    seen = app.client.get("/v1/conversations", headers=_auth(traveler)).json()["data"]
    [chat] = [c for c in seen if c["id"] == conversation]
    assert_matches_contract(chat, "Conversation")
    assert chat["kind"] == "provider"
    assert chat["title"] == "Carioca Walks"
    assert chat["provider_id"] == provider["id"]
    assert chat["can_send"] is True
    assert _say(app, traveler, conversation, "We are two adults.").status_code == 201
    inbox = app.client.get("/v1/conversations", headers=_auth(owner)).json()["data"]
    [theirs] = [c for c in inbox if c["id"] == conversation]
    assert theirs["counterpart"]["id"] == traveler_id
    app.clock.set(app.clock.now() + timedelta(minutes=5))
    assert _say(app, owner, conversation, "Olá! Happy to.").status_code == 201
    _tick(app)
    answered = app.client.get(
        f"/v1/provider-inquiries/{inquiry['id']}", headers=_auth(owner)
    ).json()
    assert answered["first_response_at"] is not None
    assert answered["viewer_side"] == "provider"

    # Provider inbox, transitions.
    open_list = app.client.get(
        f"/v1/providers/{provider['id']}/inquiries", params={"status": "open"}, headers=_auth(owner)
    )
    assert [i["id"] for i in open_list.json()["data"]] == [inquiry["id"]]
    _problem(_act(app, traveler, inquiry["id"], "accept"), 409, "inquiry_transition_invalid")
    accepted = _act(app, owner, inquiry["id"], "accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    review = {"rating": 5, "body": "Ana knows every corner of Santa Teresa."}
    _problem(
        app.client.post(
            f"/v1/provider-inquiries/{inquiry['id']}/review", headers=_auth(traveler), json=review
        ),
        409,
        "review_not_allowed",
    )
    done = _act(app, owner, inquiry["id"], "complete")
    assert done.json()["status"] == "completed"
    assert done.json()["can_review"] is False  # the provider's view
    assert app.client.get(
        f"/v1/provider-inquiries/{inquiry['id']}", headers=_auth(traveler)
    ).json()["can_review"]
    posted = app.client.post(
        f"/v1/provider-inquiries/{inquiry['id']}/review", headers=_auth(traveler), json=review
    )
    assert posted.status_code == 201, posted.text
    assert_matches_contract(posted.json(), "ProviderReview")
    _problem(
        app.client.post(
            f"/v1/provider-inquiries/{inquiry['id']}/review", headers=_auth(traveler), json=review
        ),
        409,
        "review_not_allowed",
    )
    reply = app.client.post(
        f"/v1/provider-reviews/{posted.json()['id']}/reply",
        headers=_auth(owner),
        json={"body": "Obrigada, come back soon!"},
    )
    assert reply.status_code == 200, reply.text
    profile = app.client.get(f"/v1/providers/{provider['id']}").json()
    assert profile["rating_average"] == 5.0
    assert profile["rating_count"] == 1
    reviews = app.client.get(f"/v1/providers/{provider['id']}/reviews").json()
    assert reviews["data"][0]["reply"]["body"] == "Obrigada, come back soon!"
    mine = app.client.get("/v1/users/me/inquiries", headers=_auth(traveler)).json()
    assert_matches_contract(mine, "InquiryPage")
    assert mine["data"][0]["review_id"] == posted.json()["id"]

    # A new request reuses the same chat.
    again = _inquiry(app, traveler, provider["id"], flexible_dates=True, start_date=None)
    assert again.status_code == 201, again.text
    assert again.json()["conversation_id"] == conversation
    withdrawn = _act(app, traveler, again.json()["id"], "withdraw")
    assert withdrawn.json()["status"] == "withdrawn"


@pytest.mark.req("PROV-012")
def test_blocks_suspension_and_reports(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id, provider = _approved(app)
    traveler, traveler_id = _user(app)
    inquiry = _inquiry(app, traveler, provider["id"]).json()
    conversation = inquiry["conversation_id"]

    # The provider blocks the traveler: the chat closes for both.
    blocked = app.client.put(
        f"/v1/providers/{provider['id']}/blocked-travelers/{traveler_id}", headers=_auth(owner)
    )
    assert blocked.status_code == 204, blocked.text
    _problem(_say(app, traveler, conversation), 403, "blocked_relationship")
    _problem(_say(app, owner, conversation), 403, "blocked_relationship")
    app.client.delete(
        f"/v1/providers/{provider['id']}/blocked-travelers/{traveler_id}", headers=_auth(owner)
    )
    assert _say(app, traveler, conversation).status_code == 201

    # The traveler blocks the provider: it disappears for them.
    assert (
        app.client.put(f"/v1/providers/{provider['id']}/block", headers=_auth(traveler)).status_code
        == 204
    )
    listed = app.client.get("/v1/providers", headers=_auth(traveler)).json()
    assert provider["id"] not in [p["id"] for p in listed["data"]]
    _problem(
        app.client.get(f"/v1/providers/{provider['id']}", headers=_auth(traveler)), 404, "not_found"
    )
    app.client.delete(f"/v1/providers/{provider['id']}/block", headers=_auth(traveler))

    # Reports capture evidence about the provider; staff suspend and reinstate.
    reported = _report(
        app, traveler, target_type="provider", target_id=provider["id"], reason="scam"
    )
    assert reported.status_code == 202, reported.text
    assert db_scalar(
        app.db_url,
        "SELECT target_author_id FROM content_reports WHERE id = :r",
        r=uuid.UUID(reported.json()["id"]),
    ) == uuid.UUID(owner_id)
    staff, _ = _staff(app)
    detail = app.client.get(f"/v1/admin/providers/{provider['id']}", headers=_admin(staff)).json()
    assert detail["open_report_count"] == 1
    suspended = app.client.post(
        f"/v1/admin/providers/{provider['id']}/suspend",
        headers=_admin(staff),
        json={"reason": "Several scam reports under review."},
    )
    assert suspended.status_code == 200, suspended.text
    assert app.client.get(f"/v1/providers/{provider['id']}").status_code == 404
    chats = app.client.get("/v1/conversations", headers=_auth(traveler)).json()["data"]
    [chat] = [c for c in chats if c["id"] == conversation]
    assert (chat["can_send"], chat["send_restriction"]) == (False, "provider_unavailable")
    _problem(_say(app, traveler, conversation), 403, "forbidden")
    _problem(_inquiry(app, _user(app)[0], provider["id"]), 404, "not_found")
    reinstated = app.client.post(
        f"/v1/admin/providers/{provider['id']}/reinstate", headers=_admin(staff)
    )
    assert reinstated.json()["provider"]["status"] == "approved"
    assert app.client.get(f"/v1/providers/{provider['id']}").status_code == 200


@pytest.mark.req("PROV-011", "PROV-012")
def test_staff_remove_and_restore_reviews(app: LiveApp) -> None:  # noqa: F811
    owner, _, provider = _approved(app)
    traveler, _ = _user(app)
    inquiry = _inquiry(app, traveler, provider["id"]).json()
    _act(app, owner, inquiry["id"], "accept")
    _act(app, owner, inquiry["id"], "complete")
    review = app.client.post(
        f"/v1/provider-inquiries/{inquiry['id']}/review",
        headers=_auth(traveler),
        json={"rating": 1, "body": "Terrible, call me at +55 21 99999-0000 instead"},
    ).json()
    staff, _ = _staff(app)
    removed = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(staff, **{"Idempotency-Key": str(uuid.uuid4())}),
        json={
            "target_type": "provider_review",
            "target_id": review["id"],
            "action": "remove_content",
            "reason_code": "privacy",
        },
    )
    assert removed.status_code in (200, 201), removed.text
    profile = app.client.get(f"/v1/providers/{provider['id']}").json()
    assert (profile["rating_count"], profile["rating_average"]) == (0, None)
    assert app.client.get(f"/v1/providers/{provider['id']}/reviews").json()["data"] == []
    restored = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(staff, **{"Idempotency-Key": str(uuid.uuid4())}),
        json={
            "target_type": "provider_review",
            "target_id": review["id"],
            "action": "restore_content",
            "reason_code": "privacy",
        },
    )
    assert restored.status_code in (200, 201), restored.text
    assert app.client.get(f"/v1/providers/{provider['id']}").json()["rating_count"] == 1


# ─────────────────────────────── teams ───────────────────────────────


@pytest.mark.req("PROV-005")
def test_company_team_shares_the_inbox(app: LiveApp) -> None:  # noqa: F811
    owner, _, company = _approved(app, kind="company", display_name="Rio Adventures Ltda")
    traveler, _ = _user(app)
    inquiry = _inquiry(app, traveler, company["id"]).json()
    agent, agent_id = _user(app)
    invited = app.client.post(
        f"/v1/providers/{company['id']}/members",
        headers=_auth(owner),
        json={"handle": _handle(app, agent_id), "role": "agent"},
    )
    assert invited.status_code == 201, invited.text
    assert_matches_contract(invited.json(), "ProviderMemberList")
    mine = app.client.get("/v1/users/me/providers", headers=_auth(agent)).json()
    assert_matches_contract(mine, "ProviderMembershipList")
    assert mine["data"][0]["status"] == "invited"
    # Not yet a member of the inbox.
    _problem(
        app.client.get(f"/v1/providers/{company['id']}/inquiries", headers=_auth(agent)),
        403,
        "forbidden",
    )
    accepted = app.client.post(
        f"/v1/providers/{company['id']}/members/me/accept", headers=_auth(agent)
    )
    assert accepted.status_code == 200, accepted.text
    inbox = app.client.get(f"/v1/providers/{company['id']}/inquiries", headers=_auth(agent)).json()
    assert [i["id"] for i in inbox["data"]] == [inquiry["id"]]
    assert _say(app, agent, inquiry["conversation_id"], "I'll be your guide.").status_code == 201
    # Agents can't edit or invite; they can leave.
    _problem(
        app.client.patch(
            f"/v1/providers/{company['id']}", headers=_auth(agent), json={"tagline": "x"}
        ),
        403,
        "forbidden",
    )
    left = app.client.delete(
        f"/v1/providers/{company['id']}/members/{agent_id}", headers=_auth(agent)
    )
    assert left.status_code == 204
    _problem(_say(app, agent, inquiry["conversation_id"]), 404, "not_found")
    # Guides have no team.
    guide_owner, _, guide = _approved(app, display_name="Solo Guide")
    _problem(
        app.client.post(
            f"/v1/providers/{guide['id']}/members",
            headers=_auth(guide_owner),
            json={"handle": _handle(app, agent_id), "role": "agent"},
        ),
        403,
        "forbidden",
    )


# ─────────────────────────────── housekeeping, erasure, export ───────────────────────────────


@pytest.mark.req("PROV-004", "PROV-010")
def test_housekeeping_expires_completes_and_drops_document_files(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id, provider = _approved(app)
    stale_traveler, _ = _user(app)
    stale = _inquiry(app, stale_traveler, provider["id"]).json()
    past_traveler, past_id = _user(app)
    past = _inquiry(app, past_traveler, provider["id"]).json()
    _act(app, owner, past["id"], "accept")

    later = app.clock.now() + timedelta(days=20)
    changed = _run(app, lambda s: providers_service.housekeeping(s, later))
    assert changed >= 2
    status = lambda i: db_scalar(  # noqa: E731
        app.db_url, "SELECT status FROM provider_inquiries WHERE id = :i", i=uuid.UUID(i)
    )
    assert status(stale["id"]) == "expired"
    assert status(past["id"]) == "completed"
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM notifications WHERE user_id = :u "
            "AND type = 'provider_inquiry_update'",
            u=uuid.UUID(past_id),
        )
        >= 2  # type: ignore[operator]
    )
    # Verification files go 90 days after the decision; the record stays.
    much_later = app.clock.now() + timedelta(days=95)
    _run(app, lambda s: providers_service.housekeeping(s, much_later))
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM provider_documents WHERE provider_id = :p AND media_id IS NULL "
            "AND file_deleted_at IS NOT NULL",
            p=uuid.UUID(provider["id"]),
        )
        == 1
    )
    assert owner_id


@pytest.mark.req("PROV-015")
def test_erasure_hands_companies_over_and_closes_guides(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id, company = _approved(app, kind="company", display_name="Hand Over Tours")
    manager, manager_id = _user(app)
    app.client.post(
        f"/v1/providers/{company['id']}/members",
        headers=_auth(owner),
        json={"handle": _handle(app, manager_id), "role": "manager"},
    )
    app.client.post(f"/v1/providers/{company['id']}/members/me/accept", headers=_auth(manager))
    guide_owner, guide_owner_id, guide = _approved(app, display_name="Closing Guide")

    _run(app, lambda s: providers_service.hand_over_providers(s, uuid.UUID(owner_id)))
    _run(app, lambda s: providers_service.hand_over_providers(s, uuid.UUID(guide_owner_id)))
    assert (
        db_scalar(
            app.db_url,
            "SELECT role FROM provider_members WHERE provider_id = :p AND user_id = :u",
            p=uuid.UUID(company["id"]),
            u=uuid.UUID(manager_id),
        )
        == "owner"
    )
    assert (
        db_scalar(
            app.db_url, "SELECT status FROM providers WHERE id = :p", p=uuid.UUID(company["id"])
        )
        == "approved"
    )
    assert (
        db_scalar(
            app.db_url, "SELECT status FROM providers WHERE id = :p", p=uuid.UUID(guide["id"])
        )
        == "deactivated"
    )
    assert (
        db_scalar(
            app.db_url, "SELECT tagline FROM providers WHERE id = :p", p=uuid.UUID(guide["id"])
        )
        is None
    )
    exported = _run(app, lambda s: providers_service.export_user_data(s, uuid.UUID(manager_id)))
    assert len(exported["provider_memberships"]) == 1
    assert len(exported["providers_owned"]) == 1
    assert owner
    assert guide_owner


@pytest.mark.security
@pytest.mark.req("PROV-002", "PROV-004")
def test_public_provider_schemas_never_carry_private_fields() -> None:
    from tests.contract_schemas import _components

    components = _components()["schemas"]
    private = {"legal_name", "registration_number", "review_note", "documents", "members", "email"}

    def fields(name: str) -> set[str]:
        schema = components[name]
        found = set(schema.get("properties", {}))
        for part in schema.get("allOf", []):
            if "$ref" in part:
                found |= fields(part["$ref"].rsplit("/", 1)[1])
            else:
                found |= set(part.get("properties", {}))
        return found

    for name in (
        "ProviderSummary",
        "ProviderProfile",
        "Offering",
        "ProviderReview",
        "ProviderDocument",
    ):
        assert not (fields(name) & private), name
    assert "url" not in fields("ProviderDocument")
