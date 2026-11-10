"""Pure-ASGI middleware: correlation ID, access logging, baseline security headers.

Implemented as raw ASGI (not BaseHTTPMiddleware) so context variables propagate correctly and
streaming responses are not buffered.
"""

from __future__ import annotations

import json
import logging
import re
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import INTERNAL_ERROR_DETAIL, PROBLEM_MEDIA_TYPE, ErrorCode, build_problem
from app.core.ids import uuid7
from app.core.request_context import request_id_var

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

access_logger = logging.getLogger("app.access")
logger = logging.getLogger(__name__)


def resolve_request_id(incoming: str | None) -> str:
    """Accept a well-formed client/edge request ID, otherwise generate a UUIDv7."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid7())


HSTS_VALUE = "max-age=63072000; includeSubDomains"


class RequestContextMiddleware:
    """Sets the correlation ID, writes the redacted access log, adds baseline security headers,
    and renders unexpected exceptions as problem+json *with* the request ID.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        error_type_base_url: str = "https://errors.travelbuddy.app/",
        hsts: bool = False,
    ) -> None:
        self.app = app
        self.error_type_base_url = error_type_base_url
        # HTTPS only, for two years, on the API host and its subdomains (DM-013, encryption in
        # transit). Browsers ignore it over plain HTTP, so local development is unaffected.
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming: str | None = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = resolve_request_id(incoming)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers.setdefault("x-content-type-options", "nosniff")
                headers.setdefault("referrer-policy", "no-referrer")
                if self.hsts:
                    headers.setdefault("strict-transport-security", HSTS_VALUE)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Once headers are sent we cannot replace the response; let the server abort it.
            if scope["type"] != "http" or "status" in status_holder:
                raise
            logger.exception("unhandled_exception", extra={"route": scope.get("path", "")})
            body = build_problem(
                type_base_url=self.error_type_base_url,
                code=ErrorCode.INTERNAL_ERROR,
                status=500,
                title="Internal Server Error",
                detail=INTERNAL_ERROR_DETAIL,
                instance=scope.get("path"),
            )
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", PROBLEM_MEDIA_TYPE.encode("ascii"))],
                }
            )
            await send_wrapper(
                {"type": "http.response.body", "body": json.dumps(body).encode("utf-8")}
            )
        finally:
            if scope["type"] == "http":
                route = scope.get("route")
                # Log the route template (or bare path) only; never the query string, which may
                # contain coordinates (LOC-003).
                path_template = getattr(route, "path", None) or scope.get("path", "")
                access_logger.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "route": path_template,
                        "status": status_holder.get("status", 500),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
            request_id_var.reset(token)
