"""Abuse signals filed for staff review (BL-2.07; SAFE-011, T-LOC-03)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_discovery import _destination, _start, _traveler
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _tick, _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("SAFE-011")]


def _run_detection(live: LiveApp) -> None:
    db_scalar(
        live.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'safety.abuse_signals' RETURNING 1",
    )
    _tick(live)  # schedules the job (and creates the task row on the first tick)
    db_scalar(
        live.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'safety.abuse_signals' RETURNING 1",
    )
    _tick(live)
    _tick(live)


def _system_reports(live: LiveApp, user_id: str) -> list[dict[str, Any]]:
    moderator, _ = _staff(live)
    queue = live.client.get("/v1/admin/reports", headers=_admin(moderator), params={"limit": 100})
    assert queue.status_code == 200, queue.text
    return [r for r in queue.json()["data"] if r["target_id"] == user_id and r["reporter"] is None]


def test_mass_requests_with_many_declines_are_flagged_once(app: LiveApp) -> None:  # noqa: F811
    _, spammer = _user(app)
    for index in range(16):
        _, target = _user(app)
        db_scalar(
            app.db_url,
            "INSERT INTO connection_requests (id, requester_id, recipient_id, status, context, "
            "expires_at, responded_at) VALUES (gen_random_uuid(), :a, :b, :s, 'profile', "
            "now() + interval '30 days', now()) RETURNING 1",
            a=uuid.UUID(spammer),
            b=uuid.UUID(target),
            s="declined" if index % 2 == 0 else "pending",
        )
    _run_detection(app)
    _run_detection(app)  # still open: no duplicate
    [report] = _system_reports(app, spammer)
    assert report["reason"] == "spam"
    assert report["evidence"]["signal"] == "mass_connection_requests"
    assert report["evidence"]["sent"] == 16


def test_destination_hopping_is_flagged(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _traveler(app)
    for path in ("portugal/lisbon", "japan/tokyo", "italy/rome", "france/paris"):
        assert _start(app, token, _destination(app, path)).status_code == 200
    _run_detection(app)
    [report] = _system_reports(app, user_id)
    assert report["evidence"]["signal"] == "destination_hopping"
    assert report["evidence"]["cities"] == 4


def test_ordinary_activity_is_not_flagged(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _traveler(app)
    _start(app, token, _destination(app, "portugal/lisbon"))
    _run_detection(app)
    assert _system_reports(app, user_id) == []
