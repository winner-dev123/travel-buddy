"""Pure destination rules: localization fallback, point handling, boundary shapes."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

FALLBACK_LOCALE = "en"
POINT_DECIMALS = 3  # ~110 m: device positions are coarsened before any server use (LOC-003)
SEGMENT_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NEAR = re.compile(r"^(-?\d{1,2}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)$")


def localized(texts: Mapping[str, str], preferences: Sequence[str]) -> str | None:
    """Best text for the reader (DEST-002): exact tag, then same language, then English.

    ``texts`` maps locale tags (``pt-BR``) to text; ``preferences`` is the Accept-Language order.
    """
    by_lower = {locale.lower(): text for locale, text in texts.items() if text}
    by_language: dict[str, str] = {}
    for locale, text in texts.items():
        if text:
            by_language.setdefault(locale.split("-", 1)[0].lower(), text)
    for tag in preferences:
        lowered = tag.lower()
        if lowered in by_lower:
            return by_lower[lowered]
        language = lowered.split("-", 1)[0]
        if language in by_language:
            return by_language[language]
    return by_lower.get(FALLBACK_LOCALE) or by_language.get(FALLBACK_LOCALE)


@dataclass(frozen=True, slots=True)
class Point:
    lat: float
    lng: float


def parse_near(value: str) -> Point:
    """``lat,lng`` -> point rounded to ~110 m. Raises ``ValueError`` for malformed or out-of-range
    input. The precise value must never be logged or stored (contract ``Near``)."""
    match = _NEAR.fullmatch(value.strip())
    if match is None:
        raise ValueError("near must be 'lat,lng'")
    lat, lng = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("near is out of range")
    return Point(round(lat, POINT_DECIMALS), round(lng, POINT_DECIMALS))


@dataclass(frozen=True, slots=True)
class BoundingBox:
    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("invalid latitude range")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("invalid longitude range (antimeridian boxes are not supported)")

    def contains(self, point: Point) -> bool:
        return self.south <= point.lat <= self.north and self.west <= point.lng <= self.east

    def as_multipolygon_wkt(self) -> str:
        """WKT in lng/lat order, counter-clockwise exterior ring (geography convention)."""
        s, w, n, e = self.south, self.west, self.north, self.east
        ring = f"{w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}"
        return f"MULTIPOLYGON((({ring})))"


def join_path(segments: Sequence[str]) -> str:
    return "/".join(segments)
