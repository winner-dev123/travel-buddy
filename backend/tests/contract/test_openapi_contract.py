"""Contract tests (ADR-0002): the normative OpenAPI document and realtime schemas.

* The contract is a valid OpenAPI 3.1 document.
* Every route the backend implements exists in the contract with the same method.
* Every realtime frame schema is a valid JSON Schema 2020-12 document.
* Schemas describing *other users* never expose coordinates, distances or private identity
  data (threat T-LOC-01, PRD PROF-005, LOC-009).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from fastapi import FastAPI
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.contract

CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi" / "openapi.yaml"
# Contract operations up to this phase must all be implemented (later phases may be partial),
# except the known gaps below, each tracked in docs/09. Remove an entry when it lands.
DELIVERED_PHASE = 5
PENDING_OPERATIONS = frozenset(
    {
        "GET /v1/catalog/travel-interests",
        "GET /v1/users/search",
        "GET /v1/users/{}/relationship",
        "GET /v1/groups/{}/join-requests",
        "POST /v1/groups/{}/join-requests",
        "POST /v1/groups/{}/join-requests/{}/approve",
        "POST /v1/groups/{}/join-requests/{}/reject",
        "POST /v1/billing/webhooks/apple",
        "POST /v1/billing/webhooks/google",
        "PATCH /v1/admin/destinations/{}",
    }
)
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


_METHODS = ("get", "put", "post", "patch", "delete")


def _shape(path: str) -> str:
    """The path with parameter names erased: code uses ``{post_id}``, the contract ``{postId}``."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _implemented() -> list[tuple[str, str, dict[str, Any]]]:
    """``(path, METHOD, operation)`` for every API route, from the app's generated OpenAPI
    document. FastAPI 0.16x wraps included routers, so ``app.routes`` no longer lists ``APIRoute``
    objects; a scan of it finds nothing and would pass silently. The guard below makes sure the
    routes really are seen. Development-only routes are included, so they are checked too."""
    from app.main import create_app
    from tests.conftest import make_identity_settings, make_settings

    app: FastAPI = create_app(
        make_settings(dev_idp_enabled=True, dev_billing_enabled=True),
        identity_settings=make_identity_settings(),
    )
    generated: dict[str, dict[str, Any]] = app.openapi()["paths"]
    found = [
        (path, method.upper(), operation)
        for path, item in generated.items()
        for method, operation in item.items()
        if method in _METHODS
    ]
    assert len(found) > 200, f"only {len(found)} routes seen: route discovery is broken"
    return found


def test_implemented_routes_exist_in_contract(spec: dict[str, Any]) -> None:
    contract = {_shape(path): item for path, item in spec["paths"].items()}
    missing = [
        f"{method} {path}"
        for path, method, _ in _implemented()
        if method.lower() not in contract.get(_shape(path), {})
    ]
    assert not missing, f"implemented but not in contract: {missing}"


def test_contract_routes_are_implemented(spec: dict[str, Any]) -> None:
    """The reverse: every contract operation of a delivered phase has a backend route. Later
    phases may list operations that are still to come."""
    implemented = {(_shape(path), method.lower()) for path, method, _ in _implemented()}
    absent = [
        f"{method.upper()} {path} (phase {operation.get('x-phase')})"
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in _METHODS
        and (_shape(path), method) not in implemented
        and operation.get("x-phase", 0) <= DELIVERED_PHASE
        and f"{method.upper()} {_shape(path)}" not in PENDING_OPERATIONS
    ]
    assert not absent, f"in the contract but not implemented: {absent}"
    landed = sorted(
        entry
        for entry in PENDING_OPERATIONS
        if (entry.split(" ", 1)[1], entry.split(" ", 1)[0].lower()) in implemented
    )
    assert not landed, f"implemented now; remove from PENDING_OPERATIONS: {landed}"


def test_implemented_routes_use_the_contract_rate_limit_class(spec: dict[str, Any]) -> None:
    """Each route's effective class (declared or method default) matches x-rate-limit-class."""
    from app.core.ratelimit import route_rate_class

    contract = {_shape(path): item for path, item in spec["paths"].items()}
    mismatched = []
    for path, method, operation in _implemented():
        documented = contract.get(_shape(path), {}).get(method.lower())
        if documented is None:
            continue  # reported by test_implemented_routes_exist_in_contract
        # route_rate_class reads only the declared extras and the path.
        route = cast(APIRoute, SimpleNamespace(openapi_extra=operation, path=path))
        effective, _ = route_rate_class(route, method)
        if effective.value != documented.get("x-rate-limit-class"):
            mismatched.append(
                f"{method} {path}: {effective} != {documented.get('x-rate-limit-class')}"
            )
    assert not mismatched, mismatched


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


# Challenge schemas members receive; answers, judging detail and reward secrets stay out of them.
MEMBER_CHALLENGE_SCHEMAS = (
    "Challenge",
    "ChallengePage",
    "ChallengeManagerView",
    "ChallengeHint",
    "ChallengeParticipation",
    "SubmissionResult",
    "ChallengeResults",
    "ChallengeWinner",
    "ChallengeTeam",
    "ChallengeTeamPage",
    "ChallengeDispute",
    "RewardSummary",
    "RewardFulfillment",
    "RewardFulfillmentPage",
)
FORBIDDEN_CHALLENGE_FIELDS = frozenset(
    {
        "accepted_answers",
        "answers",
        "answer_display",
        "answer_normalized",
        "judging_criteria",
        "secret",
        "secret_ciphertext",
    }
)


@pytest.mark.security
@pytest.mark.req("CHAL-008", "CHAL-015", "T-CHAL-01")
def test_member_challenge_schemas_never_carry_answers_or_secrets(spec: dict[str, Any]) -> None:
    components: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    missing = [name for name in MEMBER_CHALLENGE_SCHEMAS if name not in components]
    assert not missing, f"expected challenge schemas in contract: {missing}"
    leaks = {
        name: sorted(
            set(_iter_property_names(components[name], components, {name}))
            & FORBIDDEN_CHALLENGE_FIELDS
        )
        for name in MEMBER_CHALLENGE_SCHEMAS
    }
    leaks = {name: fields for name, fields in leaks.items() if fields}
    assert not leaks, f"member challenge schemas leak answers or secrets: {leaks}"
