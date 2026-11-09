from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import REDACTED, JsonFormatter, redact, redact_text
from app.core.request_context import request_id_var


@pytest.mark.req("LOC-003")
def test_coordinates_redacted_from_text() -> None:
    text = "GET /v1/feed?tab=nearby&near=-22.97,-43.18&lat=-22.9&lng=-43.1 200"
    redacted = redact_text(text)
    assert "-22.97" not in redacted
    assert "-43.1" not in redacted
    assert f"near={REDACTED}" in redacted


def test_tokens_and_emails_redacted_from_text() -> None:
    redacted = redact_text("Authorization: Bearer eyJhbGciOi.abc.def user ana@example.com")
    assert "eyJhbGciOi" not in redacted
    assert "ana@example.com" not in redacted


@pytest.mark.req("LOC-003")
def test_sensitive_keys_redacted_recursively() -> None:
    data = {
        "route": "/v1/feed",
        "query": {"near": "-22.9,-43.1", "tab": "nearby"},
        "headers": [{"Authorization": "Bearer x"}],
        "message": {"body": "hello there"},
    }
    result = redact(data)
    assert result["route"] == "/v1/feed"
    assert result["query"] == {"near": REDACTED, "tab": "nearby"}
    assert result["headers"] == [{"Authorization": REDACTED}]
    assert result["message"] == {"body": REDACTED}


def test_json_formatter_includes_request_id_and_redacts_extras() -> None:
    formatter = JsonFormatter("test-service")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.latitude = -22.9
    record.route = "/v1/feed"
    token = request_id_var.set("req-abcdef12")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        request_id_var.reset(token)
    assert payload["msg"] == "hello world"
    assert payload["request_id"] == "req-abcdef12"
    assert payload["service"] == "test-service"
    assert payload["latitude"] == REDACTED
    assert payload["route"] == "/v1/feed"
