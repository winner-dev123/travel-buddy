from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_all_checks_pass(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


def test_not_ready_when_a_check_fails_or_times_out() -> None:
    async def ok() -> bool:
        return True

    async def failing() -> None:
        raise ConnectionError("postgres://user:secret@db/x unreachable")

    async def slow() -> None:
        await asyncio.sleep(5)

    app = create_app(
        make_settings(readiness_timeout_seconds=0.05),
        readiness_checks={"database": failing, "redis": slow, "other": ok},
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "fail", "redis": "fail", "other": "ok"},
    }
    assert "secret" not in response.text
