"""Validate API responses against component schemas of the normative OpenAPI contract.

OpenAPI 3.1 schemas are JSON Schema 2020-12, so responses are checked with ``jsonschema`` and
local ``#/components/schemas/...`` references resolve within the contract document.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from tests.conftest import REPO_ROOT

CONTRACT_PATH = REPO_ROOT / "contracts" / "openapi" / "openapi.yaml"


@lru_cache(maxsize=1)
def _components() -> dict[str, Any]:
    spec = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    components: dict[str, Any] = spec["components"]
    return components


def assert_matches_contract(instance: Any, schema_name: str) -> None:
    root = {"$ref": f"#/components/schemas/{schema_name}", "components": _components()}
    errors = sorted(Draft202012Validator(root).iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        details = "\n".join(f"  {list(e.path)}: {e.message}" for e in errors[:10])
        raise AssertionError(f"response does not match contract schema {schema_name}:\n{details}")
