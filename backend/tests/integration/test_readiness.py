"""Readiness against real PostgreSQL and Redis (CI service containers)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

pytestmark = pytest.mark.integration


def test_ready_with_real_dependencies(test_database_url: str, test_redis_url: str) -> None:
    app = create_app(make_settings(database_url=test_database_url, redis_url=test_redis_url))
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}
