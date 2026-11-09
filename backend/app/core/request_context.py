"""Request-scoped context (correlation ID, authenticated user) carried via contextvars."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_user_id() -> str | None:
    return user_id_var.get()
