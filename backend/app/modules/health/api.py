"""Health endpoints.

* ``/health/live``: the process is up (no dependency checks; used for restarts).
* ``/health/ready``: dependencies reachable (used to route traffic). Returns 503 when any
  required check fails. Check details expose only ``ok``/``fail``, never connection strings.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

type ReadinessCheck = Callable[[], Awaitable[object]]


class LiveStatus(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyStatus(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "fail"]]


@router.get("/live", response_model=LiveStatus, summary="Liveness probe")
async def live() -> LiveStatus:
    return LiveStatus()


async def _run_check(name: str, check: ReadinessCheck, limit_seconds: float) -> tuple[str, bool]:
    try:
        async with asyncio.timeout(limit_seconds):
            await check()
    except Exception as exc:  # any failure (including TimeoutError) means "not ready"
        logger.warning("readiness_check_failed", extra={"check": name, "error": type(exc).__name__})
        return name, False
    return name, True


@router.get(
    "/ready",
    response_model=ReadyStatus,
    responses={503: {"model": ReadyStatus}},
    summary="Readiness probe",
)
async def ready(request: Request) -> JSONResponse:
    checks: Mapping[str, ReadinessCheck] = request.app.state.readiness_checks
    timeout: float = request.app.state.settings.readiness_timeout_seconds
    results = await asyncio.gather(
        *(_run_check(name, check, timeout) for name, check in checks.items())
    )
    all_ok = all(ok for _, ok in results)
    body = ReadyStatus(
        status="ready" if all_ok else "not_ready",
        checks={name: ("ok" if ok else "fail") for name, ok in results},
    )
    return JSONResponse(body.model_dump(), status_code=200 if all_ok else 503)
