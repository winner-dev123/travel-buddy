from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.core.middleware import RequestContextMiddleware, resolve_request_id


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "edge-abc-123456"})
    assert response.headers["x-request-id"] == "edge-abc-123456"


def test_invalid_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id with spaces"})
    generated = response.headers["x-request-id"]
    assert generated != "bad id with spaces"
    assert uuid.UUID(generated).version == 7


def test_request_id_generated_and_security_headers_set(client: TestClient) -> None:
    response = client.get("/health/live")
    assert uuid.UUID(response.headers["x-request-id"]).version == 7
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.req("DM-013")
def test_hsts_is_sent_outside_development() -> None:
    async def ok(scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("ok")(scope, receive, send)

    # No lifespan: the bare test app answers HTTP only.
    secure = TestClient(RequestContextMiddleware(ok, hsts=True)).get("/")
    assert secure.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
    local = TestClient(RequestContextMiddleware(ok)).get("/")
    assert "strict-transport-security" not in local.headers


def test_development_settings_do_not_send_hsts(client: TestClient) -> None:
    assert "strict-transport-security" not in client.get("/health/live").headers


def test_resolve_request_id_rejects_oversized_values() -> None:
    assert resolve_request_id("a" * 129) != "a" * 129
    assert resolve_request_id("a" * 128) == "a" * 128
