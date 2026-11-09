"""Structured JSON logging with correlation IDs and redaction of sensitive data.

Coordinates, tokens, emails and message bodies must never reach logs (threats T-LOC-07,
T-MSG-05). Redaction is applied both to structured ``extra`` fields and to message text.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_request_id, current_user_id

REDACTED = "[REDACTED]"

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "ticket",
        "secret",
        "email",
        "near",
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "coordinates",
        "body",
        "answer",
        "answer_text",
        "birth_date",
    }
)

_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    (
        re.compile(r"(?i)\b(near|lat|lng|lon|latitude|longitude)=[^&\s]+"),
        rf"\1={REDACTED}",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), REDACTED),
)

# Attributes present on every LogRecord; anything else came from ``extra=``.
_RESERVED_ATTRS: frozenset[str] = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)


def redact_text(text: str) -> str:
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys in mappings/sequences and patterns in strings."""
    if _depth > 8:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(k): (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, _depth=_depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
            "service": self._service,
        }
        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id
        user_id = current_user_id()
        if user_id:
            payload["user_id"] = user_id
        extras = {k: v for k, v in vars(record).items() if k not in _RESERVED_ATTRS}
        if extras:
            payload.update(redact(extras))
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact_text(str(record.msg))
        base = super().format(record)
        request_id = current_request_id()
        return f"{base} [request_id={request_id}]" if request_id else base


def configure_logging(*, level: str, json_output: bool, service_name: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter(service_name))
    else:
        handler.setFormatter(_ConsoleFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log includes query strings (which may carry coordinates); we emit our
    # own redacted access log from RequestContextMiddleware instead.
    logging.getLogger("uvicorn.access").disabled = True
