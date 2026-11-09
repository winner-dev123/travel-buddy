from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.middleware import resolve_request_id


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


def test_resolve_request_id_rejects_oversized_values() -> None:
    assert resolve_request_id("a" * 129) != "a" * 129
    assert resolve_request_id("a" * 128) == "a" * 128
