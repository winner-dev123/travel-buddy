"""Cloud SQL for PostgreSQL through the Cloud SQL Python Connector (ADR-0028), without the network:
the optional ``gcp`` extra is replaced by fakes in ``sys.modules``."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.db import CLOUD_SQL_SCOPE, Database, cloud_sql_connect
from tests.conftest import make_settings

INSTANCE = "travel-buddy-test:us-east1:main"


class _FakeConnector:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self.calls = calls

    async def connect_async(self, instance: str, driver: str, **kwargs: Any) -> str:
        self.calls.append(("connect", (instance, driver, kwargs)))
        return "connection"

    async def close_async(self) -> None:
        self.calls.append(("close", None))


@pytest.fixture
def fake_gcp(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def create_async_connector(**kwargs: Any) -> _FakeConnector:
        calls.append(("create", kwargs))
        return _FakeConnector(calls)

    connector = types.ModuleType("google.cloud.sql.connector")
    connector.create_async_connector = create_async_connector  # type: ignore[attr-defined]

    class _Credentials:
        @staticmethod
        def from_service_account_info(info: dict[str, Any], scopes: list[str]) -> Any:
            calls.append(("credentials", (info["client_email"], scopes)))
            return "credentials"

    service_account = types.ModuleType("google.oauth2.service_account")
    service_account.Credentials = _Credentials  # type: ignore[attr-defined]
    oauth2 = types.ModuleType("google.oauth2")
    oauth2.service_account = service_account  # type: ignore[attr-defined]
    for name, module in {
        "google.cloud.sql.connector": connector,
        "google.oauth2": oauth2,
        "google.oauth2.service_account": service_account,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


async def test_connections_go_through_the_connector_with_url_credentials(
    fake_gcp: list[tuple[str, Any]],
) -> None:
    key = json.dumps({"client_email": "api@travel-buddy-test.iam.gserviceaccount.com"})
    connect, close = cloud_sql_connect(
        INSTANCE, "postgresql+asyncpg://app:s3cret@/travelbuddy", credentials_json=key
    )
    assert await connect() == "connection"
    assert await connect() == "connection"
    await close()
    await close()  # idempotent

    kinds = [kind for kind, _ in fake_gcp]
    assert kinds == ["credentials", "create", "connect", "connect", "close"]  # one connector
    assert fake_gcp[0][1] == ("api@travel-buddy-test.iam.gserviceaccount.com", [CLOUD_SQL_SCOPE])
    assert fake_gcp[1][1] == {"credentials": "credentials", "refresh_strategy": "lazy"}
    assert fake_gcp[2][1] == (
        INSTANCE,
        "asyncpg",
        {"user": "app", "password": "s3cret", "db": "travelbuddy"},
    )


async def test_without_a_key_the_connector_uses_default_credentials(
    fake_gcp: list[tuple[str, Any]],
) -> None:
    connect, close = cloud_sql_connect(
        INSTANCE, "postgresql+asyncpg://app:pw@/db", credentials_json=None
    )
    await connect()
    await close()
    assert fake_gcp[0] == ("create", {"credentials": None, "refresh_strategy": "lazy"})


async def test_database_from_settings_uses_cloud_sql_when_an_instance_is_set(
    fake_gcp: list[tuple[str, Any]],
) -> None:
    settings = make_settings(
        database_url="postgresql+asyncpg://app:pw@/travelbuddy",
        database_cloud_sql_instance=INSTANCE,
        google_service_account_json=SecretStr(json.dumps({"client_email": "api@x.iam"})),
    )
    database = Database.from_settings(settings, pool_size=1, max_overflow=0)
    assert database.engine.url.render_as_string() == "postgresql+asyncpg://"
    assert database.engine.pool.size() == 1  # type: ignore[attr-defined]
    await database.dispose()  # no connection was opened, so the connector was never created
    assert fake_gcp == []


async def test_database_from_settings_keeps_the_url_without_cloud_sql() -> None:
    settings = make_settings(database_url="postgresql+asyncpg://u:p@db.example:5432/app")
    database = Database.from_settings(settings)
    assert database.engine.url.host == "db.example"
    assert database.engine.pool.size() == settings.database_pool_size  # type: ignore[attr-defined]
    await database.dispose()


@pytest.mark.parametrize("bad", ["main", "project:main", "Project:us-east1:main", "a:b:c:d e"])
def test_instance_connection_name_is_validated(bad: str) -> None:
    with pytest.raises(ValueError):
        make_settings(database_cloud_sql_instance=bad)
