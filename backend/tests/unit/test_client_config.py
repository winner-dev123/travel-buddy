from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract


@pytest.mark.req("I18N-001", "AUTH-009")
def test_client_config_matches_contract_and_serves_legal_versions(client: TestClient) -> None:
    response = client.get("/v1/client-config", params={"platform": "web", "app_version": "0.1.0"})
    assert response.status_code == 200
    body = response.json()
    assert_matches_contract(body, "ClientConfig")
    assert body["legal"]["terms_version"] == "2026-11-01"
    assert body["legal"]["privacy_version"] == "2026-11-01"
    assert body["legal"]["terms_url"].endswith("/legal/terms")
    assert body["minimum_age"] == 18
    assert body["supported_locales"] == ["en", "es", "pt-BR", "fr", "de"]
    assert body["feature_flags"]["traveler_discovery"] is False
    assert body["web_push_vapid_public_key"] is None
    assert body["support"] == {"email": "support@travelbuddy.app", "url": None}


@pytest.mark.parametrize(
    ("platform", "version", "required"),
    [("ios", "0.0.9", True), ("android", "0.1.0", False), ("web", "0.0.1", False)],
)
def test_update_required_only_for_outdated_native_apps(
    client: TestClient, platform: str, version: str, required: bool
) -> None:
    response = client.get(
        "/v1/client-config", params={"platform": platform, "app_version": version}
    )
    assert response.json()["update_required"] is required


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"platform": "web"},
        {"platform": "tv", "app_version": "1.0.0"},
        {"platform": "ios", "app_version": "1.0"},
    ],
)
def test_invalid_parameters_are_rejected(client: TestClient, params: dict[str, str]) -> None:
    response = client.get("/v1/client-config", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


@pytest.mark.req("AUTH-009")
@pytest.mark.req("AUTH-002", "AUTH-003")
def test_social_providers_are_announced_once_configured(client: TestClient) -> None:
    body = client.get(
        "/v1/client-config", params={"platform": "ios", "app_version": "0.1.0"}
    ).json()
    assert body["auth_providers"] == []
    configured = make_settings(auth_social_providers=["google", "apple", "google"])
    with TestClient(create_app(configured, identity_settings=make_identity_settings())) as app:
        body = app.get(
            "/v1/client-config", params={"platform": "ios", "app_version": "0.1.0"}
        ).json()
    assert_matches_contract(body, "ClientConfig")
    assert body["auth_providers"] == ["apple", "google"]
    with pytest.raises(ValueError):
        make_settings(auth_social_providers=["facebook"])


def test_support_page_is_served_once_published() -> None:
    published = make_settings(support_url="https://travelbuddy.app/support")
    with TestClient(create_app(published, identity_settings=make_identity_settings())) as client:
        body = client.get(
            "/v1/client-config", params={"platform": "ios", "app_version": "0.1.0"}
        ).json()
    assert body["support"] == {
        "email": "support@travelbuddy.app",
        "url": "https://travelbuddy.app/support",
    }
    with pytest.raises(ValueError):
        make_settings(support_url="http://travelbuddy.app/support")  # https only
