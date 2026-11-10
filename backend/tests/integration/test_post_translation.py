"""Labelled machine translation of posts (BL-4.10; POST-010, I18N-006)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.ai_assistant.provider import FakeAIProvider, ProviderError
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _create, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

TEXT = "Chegue cedo à praia, a luz é maravilhosa."


@pytest.fixture(autouse=True)
def _fresh(app: LiveApp) -> Iterator[None]:  # noqa: F811
    clear = (
        "WITH a AS (DELETE FROM ai_generations RETURNING 1), "
        "t AS (DELETE FROM post_translations RETURNING 1) "
        "SELECT (SELECT count(*) FROM a) + count(*) FROM t"
    )
    db_scalar(app.db_url, clear)
    yield
    db_scalar(app.db_url, clear)


def _consent(live: LiveApp, token: str, granted: bool = True) -> None:
    response = live.client.post(
        "/v1/users/me/consents",
        headers=_auth(token),
        json={
            "consent_type": "post_translation",
            "version": "2026-11-01",
            "granted": granted,
            "source": "settings",
        },
    )
    assert response.status_code == 201, response.text


def _post(live: LiveApp, **overrides: Any) -> str:
    author, _ = _user(live)
    created = _create(live, author, body=TEXT, language="pt-BR", **overrides)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _translate(live: LiveApp, token: str, post_id: str, target: str = "en") -> Any:
    return live.client.get(
        f"/v1/posts/{post_id}/translation", params={"target": target}, headers=_auth(token)
    )


def _fake(live: LiveApp) -> FakeAIProvider:
    provider = live.client.app.state.ai_provider  # type: ignore[attr-defined]
    assert isinstance(provider, FakeAIProvider)
    return provider


@pytest.mark.req("POST-010", "I18N-006")
def test_translation_is_labelled_cached_and_never_replaces_the_original(
    app: LiveApp,  # noqa: F811
) -> None:
    post_id = _post(app)
    reader, reader_id = _user(app)
    _problem(_translate(app, reader, post_id), 403, "consent_required")
    _consent(app, reader)

    translated = _translate(app, reader, post_id)
    assert translated.status_code == 200, translated.text
    assert_matches_contract(translated.json(), "Translation")
    body = translated.json()
    assert body["machine_translated"] is True
    assert body["source_language"] == "pt-BR"
    assert body["target_language"] == "en"
    assert body["text"] == f"[en] {TEXT}"
    assert body["provider_attribution"] is None  # the development fake is not Claude
    original = app.client.get(f"/v1/posts/{post_id}", headers=_auth(reader)).json()
    assert original["body"] == TEXT  # the original is untouched

    calls = len(_fake(app).calls)
    again = _translate(app, reader, post_id).json()
    assert again["text"] == body["text"]
    assert len(_fake(app).calls) == calls  # served from the cache
    assert TEXT in _fake(app).calls[-1].user
    telemetry = db_scalar(
        app.db_url,
        "SELECT count(*) FROM ai_generations WHERE user_id = :u AND feature = 'post_translate' "
        "AND status = 'succeeded' AND cost_micros > 0",
        u=uuid.UUID(reader_id),
    )
    assert telemetry == 1

    _problem(_translate(app, reader, post_id, target="pt"), 422, "validation_failed")
    _problem(_translate(app, reader, post_id, target="Not A Tag"), 422, "validation_failed")
    _problem(_translate(app, reader, str(uuid.uuid4())), 404, "not_found")

    _consent(app, reader, granted=False)  # withdrawing consent stops new translations
    _problem(_translate(app, reader, post_id), 403, "consent_required")


@pytest.mark.req("POST-010")
def test_private_posts_stay_private_and_failures_are_typed(app: LiveApp) -> None:  # noqa: F811
    hidden = _post(app, visibility="private")
    reader, _ = _user(app)
    _consent(app, reader)
    _problem(_translate(app, reader, hidden), 404, "not_found")

    public = _post(app)
    _fake(app).script(ProviderError("down", retryable=True))
    _problem(_translate(app, reader, public, target="de"), 503, "ai_unavailable")
    _fake(app).script("refuse")
    _problem(_translate(app, reader, public, target="de"), 502, "ai_output_invalid")
    _fake(app).script('{"text": ""}')
    _problem(_translate(app, reader, public, target="de"), 502, "ai_output_invalid")
    assert _translate(app, reader, public, target="de").json()["text"].startswith("[de] ")
