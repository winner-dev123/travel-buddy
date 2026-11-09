from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
