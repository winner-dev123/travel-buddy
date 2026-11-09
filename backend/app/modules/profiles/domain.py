"""Pure profile rules: handle and display-name generation.

Handles and display names are public. They are never derived from the email address, which
would leak part of the user's private email (PROF-005).
"""

from __future__ import annotations

import re
import unicodedata

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
