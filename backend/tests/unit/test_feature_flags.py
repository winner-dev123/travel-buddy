from __future__ import annotations

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.feature_flags import FeatureFlags, Flag, require_flag
from app.main import create_app
from tests.conftest import make_settings


def test_all_flags_default_off() -> None:
    flags = FeatureFlags()
    assert not any(flags.snapshot().values())


def test_overrides_apply() -> None:
    flags = FeatureFlags({"traveler_discovery": True})
    assert flags.is_enabled(Flag.TRAVELER_DISCOVERY)
    assert not flags.is_enabled(Flag.TRAVEL_GROUPS)


def test_unknown_flag_fails_fast() -> None:
    with pytest.raises(ValueError, match="travel_grups"):
        FeatureFlags({"travel_grups": True})


def test_unknown_flag_in_settings_fails_app_boot() -> None:
    with pytest.raises(ValueError, match="Unknown feature flag"):
        create_app(make_settings(feature_flags={"nope": True}))


def _app_with_guarded_route(enabled: bool) -> TestClient:
    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(feature_flags={"travel_groups": enabled}), readiness_checks={"db": ok}
    )

    @app.get("/_test/groups", dependencies=[Depends(require_flag(Flag.TRAVEL_GROUPS))])
    async def guarded() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_disabled_flag_blocks_route_with_problem() -> None:
    with _app_with_guarded_route(enabled=False) as client:
        response = client.get("/_test/groups")
    assert response.status_code == 403
    assert response.json()["code"] == "feature_disabled"
    assert response.json()["feature_key"] == "travel_groups"


def test_enabled_flag_allows_route() -> None:
    with _app_with_guarded_route(enabled=True) as client:
        assert client.get("/_test/groups").json() == {"ok": True}
