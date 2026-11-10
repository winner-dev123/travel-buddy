"""Retention purges and the periodic scheduler (BL-1.18, SAFE-009, docs/04 §14)."""

from __future__ import annotations

import logging
import uuid

import pytest

from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _act, _staff
from tests.integration.test_posts import _create, _tick, _user, app  # noqa: F401
from tests.integration.test_social_interactions import _comment

pytestmark = [pytest.mark.integration, pytest.mark.req("SAFE-009")]

# Every module that owns data with a retention rule registers a daily purge (BL-1.18).
REQUIRED_TASKS = {
    "retention.platform",
    "retention.identity",
    "retention.social",
    "retention.trust_safety",
    "retention.feed",
    "retention.notifications",
}


def _retention_tasks(live: LiveApp) -> set[str]:
    runner = live.client.app.state.job_runner  # type: ignore[attr-defined]
    return {task.name for task in runner._periodic if task.name.startswith("retention.")}


def _sql(live: LiveApp, statement: str, **params: object) -> object:
    return db_scalar(live.db_url, statement, **params)


def _make_due(live: LiveApp) -> None:
    _sql(live, "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' RETURNING 1")


def _count(live: LiveApp, table: str, where: str, **params: object) -> int:
    return int(_sql(live, f"SELECT count(*) FROM {table} WHERE {where}", **params))  # type: ignore[call-overload]  # noqa: S608


def test_periodic_tasks_are_enqueued_once_per_interval(
    app: LiveApp,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Production logs at INFO: a bad `extra` key fails only when the record is actually built.
    caplog.set_level(logging.INFO, logger="app")
    tasks = _retention_tasks(app)
    assert tasks >= REQUIRED_TASKS
    _tick(app)
    _make_due(app)
    before = _count(app, "asynchronous_jobs", "kind LIKE 'retention.%'")
    _tick(app)
    after_first = _count(app, "asynchronous_jobs", "kind LIKE 'retention.%'")
    assert after_first - before == len(tasks)
    names = _sql(app, "SELECT string_agg(name, ',' ORDER BY name) FROM periodic_tasks")
    assert set(str(names).split(",")) >= tasks
    _tick(app)  # not due again for a day
    assert _count(app, "asynchronous_jobs", "kind LIKE 'retention.%'") == after_first
    assert _count(
        app,
        "periodic_tasks",
        "name LIKE 'retention.%' AND next_run_at > now() + interval '23 hours'",
    ) == len(tasks)
    assert (
        _count(
            app,
            "asynchronous_jobs",
            "kind LIKE 'retention.%' AND status <> 'succeeded'",
        )
        == 0
    )


def test_expired_data_is_purged_and_live_data_kept(app: LiveApp) -> None:  # noqa: F811
    author, author_id = _user(app)
    fan, _ = _user(app)
    # Posts: one deleted 31 days ago (purged), one deleted yesterday and one live (kept).
    old_post, recent_post, live_post = (_create(app, author).json()["id"] for _ in range(3))
    for post_id in (old_post, recent_post):
        app.client.delete(f"/v1/posts/{post_id}", headers=_auth(author))
    _sql(
        app,
        "UPDATE posts SET deleted_at = now() - interval '31 days' WHERE id = :p RETURNING 1",
        p=uuid.UUID(old_post),
    )
    # Comments: a lone deleted one (purged) and a deleted parent with a live reply (kept).
    lone = _comment(app, fan, live_post).json()["id"]
    parent = _comment(app, fan, live_post).json()["id"]
    reply = _comment(app, author, live_post, parent_comment_id=parent)
    assert reply.status_code == 201, reply.text
    for comment_id in (lone, parent):
        assert (
            app.client.delete(f"/v1/comments/{comment_id}", headers=_auth(fan)).status_code == 204
        )
    _sql(
        app,
        "UPDATE comments SET deleted_at = now() - interval '31 days' "
        "WHERE id IN (:a, :b) RETURNING 1",
        a=uuid.UUID(lone),
        b=uuid.UUID(parent),
    )
    # Notifications: one 91 days old (purged).
    app.client.post(
        f"/v1/posts/{live_post}/reactions", headers=_auth(fan), json={"reaction": "like"}
    )
    _tick(app)
    _sql(
        app,
        "UPDATE notifications SET created_at = now() - interval '91 days' "
        "WHERE user_id = :u RETURNING 1",
        u=uuid.UUID(author_id),
    )
    # Sessions: the fan's session revoked 91 days ago (purged); the author's is live (kept).
    app.client.post("/v1/auth/logout", headers=_auth(fan), json={"all_sessions": True})
    _sql(
        app,
        "UPDATE user_sessions SET revoked_at = now() - interval '91 days' "
        "WHERE revoked_at IS NOT NULL RETURNING 1",
    )
    # Moderation: a permanent restriction from 4 years ago stays (still in force); a 4-year-old
    # warning goes.
    moderator, _ = _staff(app)
    base = {"target_type": "user", "target_id": author_id, "reason_code": "spam"}
    _act(app, moderator, **base, action="warn")
    _act(app, moderator, **base, action="restrict", restriction_kind="posting_limited")
    _sql(
        app,
        "UPDATE moderation_actions SET created_at = now() - interval '4 years' "
        "WHERE target_id = :u RETURNING 1",
        u=uuid.UUID(author_id),
    )

    _make_due(app)
    _tick(app)  # enqueues the purges
    _tick(app)  # and runs any left over

    assert _count(app, "posts", "id = :p", p=uuid.UUID(old_post)) == 0
    assert _count(app, "posts", "id = :p", p=uuid.UUID(recent_post)) == 1
    assert _count(app, "posts", "id = :p", p=uuid.UUID(live_post)) == 1
    assert _count(app, "comments", "id = :c", c=uuid.UUID(lone)) == 0
    assert _count(app, "comments", "id = :c", c=uuid.UUID(parent)) == 1
    # The 91-day-old reaction notice is gone; the moderation notices created since are kept.
    assert (
        _count(
            app,
            "notifications",
            "user_id = :u AND type = 'post_reaction'",
            u=uuid.UUID(author_id),
        )
        == 0
    )
    assert _count(app, "notifications", "user_id = :u", u=uuid.UUID(author_id)) == 2
    assert _count(app, "user_sessions", "revoked_at IS NOT NULL") == 0
    assert _count(app, "user_sessions", "user_id = :u", u=uuid.UUID(author_id)) == 1
    remaining = _sql(
        app,
        "SELECT string_agg(action, ',') FROM moderation_actions WHERE target_id = :u",
        u=uuid.UUID(author_id),
    )
    assert remaining == "restrict"
