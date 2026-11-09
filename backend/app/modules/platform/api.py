"""Internal job endpoints and the after-response tick (BL-1.09).

Serverless deployments have no long-running worker, so jobs advance from two triggers:
* ``GET|POST /internal/jobs/tick`` with ``Authorization: Bearer $CRON_SECRET`` (Vercel Cron sends
  GET with exactly this header). Disabled (404) when ``CRON_SECRET`` is unset.
* :class:`AfterResponseTickMiddleware`: once a response that recorded outbox events has been sent,
  run a short bounded tick (``JOBS_INLINE_AFTER_RESPONSE``). Best effort only.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import AppError, ErrorCode
from app.modules.platform.service import JobRunner, track_outbox_events

logger = logging.getLogger(__name__)

internal_router = APIRouter(prefix="/internal", tags=["internal"])


class JobTickCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    relayed: int
    succeeded: int
    retried: int
    dead: int
    recovered: int


class JobTickResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: JobTickCounts


def _authorize_cron(request: Request) -> None:
    secret = request.app.state.settings.cron_secret
    if secret is None:
        raise AppError(ErrorCode.NOT_FOUND, "Not found.")
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    expected = secret.get_secret_value().encode()
    if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip().encode(), expected):
        raise AppError(
            ErrorCode.UNAUTHENTICATED,
            "Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@internal_router.api_route("/jobs/tick", methods=["GET", "POST"], response_model=JobTickResult)
async def jobs_tick(request: Request) -> JobTickResult:
    _authorize_cron(request)
    runner: JobRunner = request.app.state.job_runner
    result = await runner.tick(budget_seconds=request.app.state.settings.jobs_tick_budget_seconds)
    return JobTickResult.model_validate({"data": result.as_dict()})


class AfterResponseTickMiddleware:
    """Pure ASGI: runs ``runner.tick`` after the response has been sent, only for requests that
    recorded outbox events. Failures are logged and never affect the (already sent) response."""

    def __init__(self, app: ASGIApp, *, runner: JobRunner, budget_seconds: float) -> None:
        self.app = app
        self.runner = runner
        self.budget_seconds = budget_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        signal = track_outbox_events()
        await self.app(scope, receive, send)
        if not signal.recorded:
            return
        try:
            await self.runner.tick(budget_seconds=self.budget_seconds, max_jobs=10)
        except Exception:
            logger.exception("after-response job tick failed")
