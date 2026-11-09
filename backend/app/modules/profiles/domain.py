"""Pure profile rules: handle and display-name generation.

Handles and display names are public. They are never derived from the email address, which
would leak part of the user's private email (PROF-005).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

HANDLE_PATTERN = re.compile(r"^[a-z0-9_.]{3,30}$")
HANDLE_BASE_MAX = 24  # leaves room for a numeric suffix
DISPLAY_NAME_MAX = 50
DEFAULT_HANDLE_BASE = "traveler"
DEFAULT_DISPLAY_NAME = "Traveler"


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def handle_base(name: str | None) -> str:
    """A valid handle stem (3..24 chars) from the IdP display name.

    Uniqueness is the caller's job.
    """
    if name:
        candidate = re.sub(r"[^a-z0-9_.]", "", _ascii_fold(name).lower().replace(" ", "."))
        candidate = re.sub(r"\.{2,}", ".", candidate).strip("._")[:HANDLE_BASE_MAX]
        if len(candidate) >= 3:
            return candidate
    return DEFAULT_HANDLE_BASE


def handle_with_suffix(base: str, suffix: int) -> str:
    if suffix < 0:
        raise ValueError("suffix must be non-negative")
    handle = f"{base[:HANDLE_BASE_MAX]}{suffix}"
    if not HANDLE_PATTERN.fullmatch(handle):
        raise ValueError(f"invalid handle: {handle!r}")
    return handle


def default_display_name(name: str | None) -> str:
    if name and name.strip():
        return " ".join(name.split())[:DISPLAY_NAME_MAX]
    return DEFAULT_DISPLAY_NAME


# ─────────────────────────────── profile edits (BL-1.04) ───────────────────────────────

HANDLE_CHANGE_INTERVAL = timedelta(days=30)  # PROF-003
BIO_MAX = 300
HOME_REGION_MAX = 100
INTEREST_MAX = 40

# Handles that could impersonate staff or the product, or collide with routes. Compared after
# removing "." and "_" so "a.d.m.i.n" or "travel_buddy" are caught too.
_RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "help",
        "me",
        "mod",
        "moderator",
        "moderators",
        "null",
        "official",
        "root",
        "security",
        "settings",
        "staff",
        "support",
        "system",
        "team",
        "undefined",
        "www",
    }
)
_RESERVED_FRAGMENTS = ("travelbuddy",)


def is_reserved_handle(handle: str) -> bool:
    squashed = handle.lower().replace(".", "").replace("_", "")
    return squashed in _RESERVED_HANDLES or any(f in squashed for f in _RESERVED_FRAGMENTS)


def next_handle_change_at(handle_changed_at: datetime | None) -> datetime | None:
    """When the next handle change is allowed; ``None`` means now (generated handle)."""
    return handle_changed_at + HANDLE_CHANGE_INTERVAL if handle_changed_at else None


def _strip_invisible(text: str) -> str:
    # Control and format characters (bidi overrides, zero-width) enable spoofing and break layout.
    return "".join(ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf"} or ch == "\n")


def clean_display_name(value: str) -> str:
    """Single line, collapsed whitespace, no invisible characters. Raises if nothing remains."""
    cleaned = " ".join(_strip_invisible(value).split())
    if not cleaned:
        raise ValueError("display_name must contain visible characters")
    if len(cleaned) > DISPLAY_NAME_MAX:
        raise ValueError(f"display_name must be at most {DISPLAY_NAME_MAX} characters")
    return cleaned


def clean_optional_text(value: str | None, *, max_length: int, multiline: bool) -> str | None:
    """Trim, drop invisible characters; empty becomes ``None``."""
    if value is None:
        return None
    text = _strip_invisible(value.replace("\r\n", "\n").replace("\r", "\n"))
    if multiline:
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n")))
    else:
        text = " ".join(text.split())
    text = text.strip()
    if len(text) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    return text or None


def clean_tags(values: list[str], *, max_length: int) -> list[str]:
    """Collapse whitespace, drop empties, de-duplicate case-insensitively (first spelling wins)."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        tag = " ".join(_strip_invisible(raw).split())
        if not tag:
            continue
        if len(tag) > max_length:
            raise ValueError(f"each entry must be at most {max_length} characters")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def dedupe(values: list[str]) -> list[str]:
    """Order-preserving, case-insensitive de-duplication for codes such as locale tags."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result
