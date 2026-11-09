from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv
from tests.conftest import ed25519_test_pem, make_identity_settings, make_settings

STRONG_KEY = SecretStr("s" * 48)


def _production(**overrides: object) -> object:
    values: dict[str, object] = {
        "app_env": AppEnv.PRODUCTION,
        "cursor_signing_key": STRONG_KEY,
        "platform_jwt_private_key": SecretStr(ed25519_test_pem()),
    }
    values.update(overrides)
    return make_settings(**values)


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_dev_identity_provider_refused_outside_dev(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="DEV_IDP_ENABLED"):
        make_settings(app_env=env, dev_idp_enabled=True, cursor_signing_key=STRONG_KEY)


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_dev_billing_refused_outside_dev(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="DEV_BILLING_ENABLED"):
        make_settings(app_env=env, dev_billing_enabled=True, cursor_signing_key=STRONG_KEY)


def test_default_cursor_key_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="CURSOR_SIGNING_KEY"):
        make_settings(app_env=AppEnv.PRODUCTION)


def test_valid_production_settings() -> None:
    settings = _production()
    assert settings.is_production_like  # type: ignore[attr-defined]
    assert not settings.expose_api_docs  # type: ignore[attr-defined]


@pytest.mark.req("AUTH-007")
def test_platform_signing_key_required_in_production() -> None:
    with pytest.raises(ValidationError, match="PLATFORM_JWT_PRIVATE_KEY"):
        _production(platform_jwt_private_key=None)


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_identity_production_guard(env: AppEnv) -> None:
    issuer = {
        "issuer": "https://idp.example.com/",
        "audiences": ["travelbuddy"],
        "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
    }
    with pytest.raises(ValidationError, match="REFRESH_TOKEN_DERIVATION_KEY"):
        make_identity_settings(app_env=env, oidc_issuers=[issuer])
    with pytest.raises(ValidationError, match="OIDC_ISSUERS"):
        make_identity_settings(app_env=env, refresh_token_derivation_key=STRONG_KEY)
    ok = make_identity_settings(
        app_env=env, refresh_token_derivation_key=STRONG_KEY, oidc_issuers=[issuer]
    )
    assert ok.oidc_issuers[0].method == "oidc"


def test_development_allows_dev_adapters() -> None:
    settings = make_settings(
        app_env=AppEnv.DEVELOPMENT, dev_idp_enabled=True, dev_billing_enabled=True
    )
    assert settings.dev_idp_enabled
    assert settings.expose_api_docs


def test_api_docs_hidden_in_production(client: object) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    async def ok() -> bool:
        return True

    app = create_app(
        _production(),  # type: ignore[arg-type]
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
    )
    with TestClient(app) as prod_client:
        assert prod_client.get("/v1/openapi.json").status_code == 404
        assert prod_client.get("/v1/docs").status_code == 404
        # The development-only IdP is not mounted outside development/test.
        assert prod_client.get("/v1/dev/idp/jwks.json").status_code == 404
