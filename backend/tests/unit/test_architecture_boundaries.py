"""Module boundary rules (ADR-0001, architecture section 4).

1. ``app.core`` never imports ``app.modules``.
2. A module imports another module only through its public ``service``, ``events`` or ``schemas``.
3. Module dependencies follow the layer DAG (strictly downward).
4. Pure domain files perform no I/O (no framework, ORM or client imports).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app

APP_ROOT = Path(app.__file__).resolve().parent
MODULES_ROOT = APP_ROOT / "modules"

PUBLIC_SUBMODULES = frozenset({"service", "events", "schemas"})

# Architecture section 4.3. Every module directory must be registered here.
LAYERS: dict[str, int] = {
    "platform": 1,
    "observability": 1,
    "media": 1,
    "destinations": 2,
    "billing": 2,
    "profiles": 2,
    "identity": 3,
    "trust_safety": 3,
    "location": 3,
    "connections": 4,
    "social": 4,
    "trips": 4,
    "guides": 4,
    "messaging": 5,
    "groups": 5,
    "feed": 5,
    "discovery": 5,
    "notifications": 5,
    "group_chat": 6,
    "challenges": 6,
    "ai_assistant": 6,
    "admin": 7,
    "client_config": 7,
    "health": 7,
}

# Pure domain logic: state machines, policies, evaluators.
PURE_FILE_NAMES = frozenset({"domain.py", "entitlements.py"})
IO_PACKAGES = frozenset(
    {"sqlalchemy", "fastapi", "starlette", "redis", "httpx", "asyncpg", "alembic", "geoalchemy2"}
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(APP_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = (
        _module_name(path) if path.name == "__init__.py" else _module_name(path).rsplit(".", 1)[0]
    )
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".")
                base = ".".join(base_parts[: len(base_parts) - (node.level - 1)])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            found.append(module)
            # "from app.modules.x import service" imports a submodule by name.
            found.extend(f"{module}.{alias.name}" for alias in node.names)
    return found


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _owning_module(path: Path) -> str | None:
    try:
        return path.relative_to(MODULES_ROOT).parts[0]
    except ValueError:
        return None


def test_every_module_is_registered_in_layers() -> None:
    present = {p.name for p in MODULES_ROOT.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert present <= set(LAYERS), (
        f"register new modules in LAYERS: {sorted(present - set(LAYERS))}"
    )


def test_core_does_not_import_modules() -> None:
    offenders = [
        f"{path.relative_to(APP_ROOT)} -> {name}"
        for path in _python_files(APP_ROOT / "core")
        for name in _imports(path)
        if name.startswith("app.modules")
    ]
    assert not offenders, offenders


def _cross_module_imports() -> list[tuple[Path, str, str, str | None]]:
    """(file, own module, other module, submodule-or-None) for each cross-module import."""
    results: list[tuple[Path, str, str, str | None]] = []
    for path in _python_files(MODULES_ROOT):
        own = _owning_module(path)
        if own is None or own == "__init__.py":
            continue
        for name in _imports(path):
            parts = name.split(".")
            if len(parts) < 3 or parts[:2] != ["app", "modules"]:
                continue
            other = parts[2]
            if other == own:
                continue
            submodule = parts[3] if len(parts) > 3 else None
            results.append((path, own, other, submodule))
    return results


def test_modules_use_only_public_interfaces_of_other_modules() -> None:
    offenders = [
        f"{path.relative_to(APP_ROOT)} imports app.modules.{other}.{sub or ''}"
        for path, _own, other, sub in _cross_module_imports()
        if sub is not None and sub not in PUBLIC_SUBMODULES
    ]
    assert not offenders, offenders


def test_module_dependencies_point_strictly_downward() -> None:
    offenders = [
        f"{own} (L{LAYERS[own]}) -> {other} (L{LAYERS.get(other, '?')})"
        for _path, own, other, _sub in _cross_module_imports()
        if LAYERS.get(other, 99) >= LAYERS[own]
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    "path",
    [p for p in _python_files(MODULES_ROOT) if p.name in PURE_FILE_NAMES],
    ids=lambda p: str(p.relative_to(APP_ROOT)),
)
def test_pure_domain_files_have_no_io_imports(path: Path) -> None:
    offenders = [n for n in _imports(path) if n.split(".")[0] in IO_PACKAGES]
    assert not offenders, offenders
