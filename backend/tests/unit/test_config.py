from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv
from tests.conftest import make_settings

STRONG_KEY = SecretStr("s" * 48)


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
    settings = make_settings(app_env=AppEnv.PRODUCTION, cursor_signing_key=STRONG_KEY)
    assert settings.is_production_like
    assert not settings.expose_api_docs


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
        make_settings(app_env=AppEnv.PRODUCTION, cursor_signing_key=STRONG_KEY),
        readiness_checks={"db": ok},
    )
    with TestClient(app) as prod_client:
        assert prod_client.get("/v1/openapi.json").status_code == 404
        assert prod_client.get("/v1/docs").status_code == 404
