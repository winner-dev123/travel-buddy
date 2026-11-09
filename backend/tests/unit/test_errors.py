from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import PROBLEM_MEDIA_TYPE, AppError, ErrorCode
from tests.conftest import make_settings


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3)


@pytest.fixture
def error_client() -> Iterator[TestClient]:
    from app.main import create_app

    async def ok() -> bool:
        return True

    app: FastAPI = create_app(make_settings(), readiness_checks={"db": ok})

    @app.get("/_test/app-error")
    async def app_error() -> None:
        raise AppError(
            ErrorCode.ENTITLEMENT_REQUIRED,
            "Creating travel groups requires an active Premium subscription.",
            title="Premium required",
            extensions={"feature_key": "groups.create", "status": 999},
        )

    @app.post("/_test/validate")
    async def validate(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_app_error_renders_problem_details(error_client: TestClient) -> None:
    response = error_client.get("/_test/app-error", headers={"X-Request-ID": "req-12345678"})

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["code"] == "entitlement_required"
    assert body["type"] == "https://errors.travelbuddy.app/entitlement_required"
    assert body["title"] == "Premium required"
    assert body["status"] == 403
    assert body["instance"] == "/_test/app-error"
    assert body["request_id"] == "req-12345678"
    assert body["feature_key"] == "groups.create"


def test_extensions_cannot_override_standard_members(error_client: TestClient) -> None:
    body = error_client.get("/_test/app-error").json()
    assert body["status"] == 403  # extension "status": 999 ignored


def test_validation_errors_list_fields(error_client: TestClient) -> None:
    response = error_client.post("/_test/validate", json={"name": "ab", "unexpected": 1})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    fields = {e["field"] for e in body["errors"]}
    assert {"name", "unexpected"} <= fields


def test_unknown_route_is_problem_not_found(error_client: TestClient) -> None:
    response = error_client.get("/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_unhandled_exception_hides_internal_detail(error_client: TestClient) -> None:
    response = error_client.get("/_test/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert body["request_id"] == response.headers["x-request-id"]


def test_every_error_code_has_a_default_status() -> None:
    for code in ErrorCode:
        assert AppError(code).status >= 400
