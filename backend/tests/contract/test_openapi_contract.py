"""Contract tests (ADR-0002): the normative OpenAPI document and realtime schemas.

* The contract is a valid OpenAPI 3.1 document.
* Every route the backend implements exists in the contract with the same method.
* Every realtime frame schema is a valid JSON Schema 2020-12 document.
* Schemas describing *other users* never expose coordinates, distances or private identity
  data (threat T-LOC-01, PRD PROF-005, LOC-009).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.contract

CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi" / "openapi.yaml"
REALTIME_DIR = REPO_ROOT / "contracts" / "realtime"

# Property names that must never appear in schemas describing another user.
FORBIDDEN_PERSON_FIELDS = frozenset(
    {
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "coordinates",
        "location",
        "point",
        "distance",
        "distance_m",
        "distance_km",
        "email",
        "birth_date",
        "birth_year",
        "phone",
        "last_ip",
        "session_id",
    }
)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    assert CONTRACT_PATH.exists(), f"missing contract: {CONTRACT_PATH}"
    loaded = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_contract_is_valid_openapi_31(spec: dict[str, Any]) -> None:
    assert str(spec["openapi"]).startswith("3.1")
    validate(spec)


def test_implemented_routes_exist_in_contract(spec: dict[str, Any]) -> None:
    from app.main import create_app
    from tests.conftest import make_identity_settings, make_settings

    # Development-only routes included, so they are checked too.
    app: FastAPI = create_app(
        make_settings(dev_idp_enabled=True), identity_settings=make_identity_settings()
    )
    contract_paths: dict[str, dict[str, Any]] = spec["paths"]
    missing = [
        f"{method} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"})
        if method.lower() not in contract_paths.get(route.path, {})
    ]
    assert not missing, f"implemented but not in contract: {missing}"


def _enum(spec: dict[str, Any], name: str) -> set[str]:
    return set(spec["components"]["schemas"][name]["enum"])


def test_platform_permissions_match_backend(spec: dict[str, Any]) -> None:
    from app.core.security.principal import Permission

    assert _enum(spec, "PlatformPermission") == {p.value for p in Permission}


def test_platform_roles_match_backend(spec: dict[str, Any]) -> None:
    from app.core.security.principal import PlatformRole

    assert _enum(spec, "PlatformRole") == {r.value for r in PlatformRole}


def test_backend_error_codes_are_declared_in_contract(spec: dict[str, Any]) -> None:
    from app.core.errors import ErrorCode

    undeclared = {c.value for c in ErrorCode} - _enum(spec, "ErrorCode")
    assert not undeclared, f"backend emits codes missing from the contract: {sorted(undeclared)}"


def test_reserved_client_codes_are_never_backend_codes(spec: dict[str, Any]) -> None:
    from app.core.errors import ErrorCode

    reserved = set(spec["components"]["schemas"]["ErrorCode"].get("x-reserved-codes", []))
    assert not reserved & {c.value for c in ErrorCode}


def test_admin_operations_declare_a_known_permission(spec: dict[str, Any]) -> None:
    known = _enum(spec, "PlatformPermission")
    problems = []
    for path, item in spec["paths"].items():
        if not path.startswith("/v1/admin/"):
            continue
        for method, op in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            permission = op.get("x-platform-permission")
            if permission not in known:
                problems.append(f"{method.upper()} {path}: {permission!r}")
    assert not problems, problems


@pytest.mark.req("ADM-009")
def test_admin_mutations_require_audit_justification(spec: dict[str, Any]) -> None:
    missing = []
    for path, item in spec["paths"].items():
        if not path.startswith("/v1/admin/"):
            continue
        for method, op in item.items():
            if method not in {"post", "put", "patch", "delete"}:
                continue
            refs = {p.get("$ref", "") for p in op.get("parameters", [])}
            if "#/components/parameters/AuditJustification" not in refs:
                missing.append(f"{method.upper()} {path}")
    assert not missing, missing


def _realtime_schemas() -> list[Path]:
    return sorted(REALTIME_DIR.glob("*.schema.json"))


def test_realtime_schemas_exist() -> None:
    assert _realtime_schemas(), f"no realtime schemas in {REALTIME_DIR}"


@pytest.mark.parametrize("path", _realtime_schemas(), ids=lambda p: p.name)
def test_realtime_schema_is_valid(path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def _iter_property_names(schema: Any, components: dict[str, Any], seen: set[str]) -> Iterator[str]:
    """Yield property names reachable from ``schema`` (following local $refs once)."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                yield from _iter_property_names(components.get(name, {}), components, seen)
            return
        for key, value in schema.get("properties", {}).items():
            yield key
            yield from _iter_property_names(value, components, seen)
        for keyword in ("items", "additionalProperties", "allOf", "anyOf", "oneOf"):
            child = schema.get(keyword)
            if isinstance(child, list):
                for item in child:
                    yield from _iter_property_names(item, components, seen)
            elif isinstance(child, dict):
                yield from _iter_property_names(child, components, seen)


def _person_schema_names(components: dict[str, Any]) -> list[str]:
    """Schemas that describe other users (by naming convention in the contract)."""
    markers = ("PublicProfile", "Traveler", "UserSummary", "Member", "Participant", "Author")
    return sorted(
        name
        for name in components
        if any(marker in name for marker in markers) and not name.startswith("My")
    )


@pytest.mark.security
@pytest.mark.req("PROF-005", "LOC-009", "DISC-004")
def test_other_user_schemas_never_expose_location_or_private_identity(
    spec: dict[str, Any],
) -> None:
    components: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    person_schemas = _person_schema_names(components)
    assert person_schemas, "expected PublicProfile/DiscoveredTraveler-style schemas in contract"
    leaks = {
        name: sorted(
            set(_iter_property_names(components[name], components, {name}))
            & FORBIDDEN_PERSON_FIELDS
        )
        for name in person_schemas
    }
    leaks = {name: fields for name, fields in leaks.items() if fields}
    assert not leaks, f"person schemas leak sensitive fields: {leaks}"
