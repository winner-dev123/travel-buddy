"""Keyword filter for direct messages from new connections (SAFE-006, T-MSG-03)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_messaging import _pair, _send, _sent
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _problem, _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("SAFE-006")]

FILTER = "/v1/admin/safety/message-filter"


@pytest.fixture(autouse=True)
def _default_filter(app: LiveApp) -> Iterator[None]:  # noqa: F811
    """Each test starts from the code defaults and leaves no policy row behind."""
    reset = "WITH d AS (DELETE FROM message_filter_policies RETURNING 1) SELECT count(*) FROM d"
    db_scalar(app.db_url, reset)
    yield
    db_scalar(app.db_url, reset)


def _filtered(response: Any) -> None:
    problem = _problem(response, 422, "validation_failed")
    assert problem["errors"][0]["code"] == "message_filtered"
    assert problem["errors"][0]["field"] == "/body"


def _age_connection(live: LiveApp, a: str, b: str, days: int) -> None:
    db_scalar(
        live.db_url,
        "UPDATE user_connections SET connected_at = now() - make_interval(days => :d) "
        "WHERE (user_low_id, user_high_id) IN ((:a, :b), (:b, :a)) RETURNING 1",
        d=days,
        a=uuid.UUID(a),
        b=uuid.UUID(b),
    )


def test_new_connections_cannot_send_filtered_terms(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, bo_id, conversation = _pair(app)
    _filtered(_send(app, ana, conversation, "hey, s.e.n.d n.u.d.e.s"))
    friendly = _sent(app, ana, conversation, "Coffee at the miradouro tomorrow?")
    # Editing a sent message into a filtered one is refused too.
    edit = app.client.patch(
        f"/v1/conversations/{conversation}/messages/{friendly['id']}",
        headers=_auth(ana),
        json={"body": "buy me a gift card first"},
    )
    _filtered(edit)

    # After a week the connection is no longer new: the filter steps aside.
    _age_connection(app, ana_id, bo_id, days=8)
    assert _send(app, bo, conversation, "I lost my gift card at the hostel").status_code == 201


@pytest.mark.req("ADM-007", "ADM-008")
def test_staff_manage_the_terms_and_the_window(app: LiveApp) -> None:  # noqa: F811
    admin, admin_id = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    _problem(app.client.get(FILTER, headers=_admin(moderator)), 403, "forbidden")

    current = app.client.get(FILTER, headers=_admin(admin))
    assert current.status_code == 200, current.text
    assert_matches_contract(current.json(), "MessageFilterPolicy")
    assert current.json()["version"] == 0
    assert "send nudes" in current.json()["terms"]
    assert current.json()["new_connection_days"] == 7

    saved = app.client.put(
        FILTER,
        headers=_admin(admin),
        json={"terms": ["Pásame tu número", "send nudes"], "new_connection_days": 30, "version": 0},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["terms"] == ["pasame tu numero", "send nudes"]
    assert saved.json()["version"] == 1
    assert saved.json()["updated_by"] == admin_id
    stale = app.client.put(
        FILTER,
        headers=_admin(admin),
        json={"terms": [], "new_connection_days": 7, "version": 0},
    )
    _problem(stale, 409, "conflict")
    _problem(
        app.client.put(
            FILTER,
            headers=_admin(admin),
            json={"terms": ["x" * 61], "new_connection_days": 7, "version": 1},
        ),
        422,
        "validation_failed",
    )

    # The new list and window apply to the next message: 20 days is still "new" with 30.
    ana, ana_id, _bo, bo_id, conversation = _pair(app)
    _age_connection(app, ana_id, bo_id, days=20)
    _filtered(_send(app, ana, conversation, "Pásame tu número, porfa"))
    assert _send(app, ana, conversation, "Gift card?").status_code == 201  # removed term

    audit = db_scalar(
        app.db_url,
        "SELECT metadata->>'added' FROM audit_logs WHERE action = 'safety.message_filter.updated' "
        "ORDER BY occurred_at DESC LIMIT 1",
    )
    assert audit == '["pasame tu numero"]'


def test_connection_request_notes_are_filtered_too(app: LiveApp) -> None:  # noqa: F811
    """Notes reach people who aren't connected at all."""
    sender, _ = _user(app)
    _recipient, recipient_id = _user(app)
    refused = app.client.post(
        "/v1/connections/requests",
        headers={**_auth(sender), "Idempotency-Key": str(uuid.uuid4())},
        json={"recipient_id": recipient_id, "context": "profile", "note": "S.E.N.D nudes?"},
    )
    problem = _problem(refused, 422, "validation_failed")
    assert problem["errors"][0] == {
        "field": "/note",
        "code": "message_filtered",
        "message": "This note can't be sent. Keep it friendly.",
    }
