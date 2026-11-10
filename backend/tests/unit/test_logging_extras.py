"""No logging call passes a reserved LogRecord attribute in ``extra`` (it raises at INFO)."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import app

APP_ROOT = Path(app.__file__).resolve().parent
RESERVED = set(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None).__dict__) | {
    "message",
    "asctime",
}


def test_extra_keys_never_shadow_log_record_attributes() -> None:
    found = []
    for path in APP_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                    found += [
                        f"{path.relative_to(APP_ROOT)}:{node.lineno} {key.value}"
                        for key in keyword.value.keys
                        if isinstance(key, ast.Constant) and key.value in RESERVED
                    ]
    assert found == []
