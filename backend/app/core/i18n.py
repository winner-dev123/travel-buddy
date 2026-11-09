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


def parse_accept_language(header: str | None, *, limit: int = 8) -> list[str]:
    """Language tags from an ``Accept-Language`` header, best first (RFC 9110 q-values).

    Malformed entries and ``*`` are skipped; at most ``limit`` tags are returned.
    """
    if not header:
        return []
    weighted: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")[:32]):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip()
        if not tag or tag == "*" or len(tag) > 35:
            continue
        quality = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                quality = float(params[2:])
            except ValueError:
                continue
        if quality <= 0:
            continue
        weighted.append((-quality, index, tag))
    return [tag for _, _, tag in sorted(weighted)][:limit]
