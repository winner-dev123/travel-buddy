"""Locales the product UI ships in (I18N-001/002), shared by client config and preferences."""

from __future__ import annotations

from typing import Final

SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("en", "es", "pt-BR", "fr", "de")
DEFAULT_LOCALE: Final = "en"
LOCALE_TAG_PATTERN: Final = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"


def negotiate_ui_locale(tag: str | None) -> str:
    """Best supported UI locale for a BCP 47 tag: exact (case-insensitive), then language, then
    the default. ``pt-PT`` → ``pt-BR``, ``de-AT`` → ``de``, ``ja`` → ``en``."""
    if not tag:
        return DEFAULT_LOCALE
    lowered = tag.lower()
    for supported in SUPPORTED_LOCALES:
        if supported.lower() == lowered:
            return supported
    language = lowered.split("-", 1)[0]
    for supported in SUPPORTED_LOCALES:
        if supported.lower().split("-", 1)[0] == language:
            return supported
    return DEFAULT_LOCALE
