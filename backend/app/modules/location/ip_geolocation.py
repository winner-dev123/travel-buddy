"""Approximate location from the caller's IP address (LOC-010, ADR-0030).

The lookup is local: a DB-IP "IP to City Lite" database (CC BY 4.0, https://db-ip.com) read with
``maxminddb``, so no address leaves the server. Only the Companions map uses it, as a starting
point the traveller can see and correct; it never places anyone in discovery or the feed by itself
(LOC-004). The address and the looked-up point are used for one request and are never stored or
logged.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import maxminddb

logger = logging.getLogger(__name__)

# Shown next to anything derived from the database (CC BY 4.0 attribution).
ATTRIBUTION = "IP geolocation by DB-IP (db-ip.com)"


@dataclass(frozen=True, slots=True, repr=False)
class IpLocation:
    """What the database knows about an address: about a city, never a street."""

    lat: float
    lng: float
    city: str | None
    country_code: str | None
    country_names: Mapping[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # keep the point out of logs and tracebacks
        return "IpLocation(<redacted>)"

    __str__ = __repr__

    def country_name(self, preferences: Sequence[str]) -> str | None:
        """The country's name in the first preferred language the database has, else English."""
        for tag in (*preferences, "en"):
            name = self.country_names.get(tag) or self.country_names.get(tag.split("-")[0])
            if name:
                return name
        return None


class IpGeolocator(Protocol):
    def locate(self, address: str) -> IpLocation | None: ...


class NoIpGeolocation:
    """Used when no database is configured: every lookup is unknown."""

    def locate(self, address: str) -> IpLocation | None:
        return None


def public_address(value: str) -> str | None:
    """A routable address from ``client_ip()``: an IPv6 /64 counts as its first address.
    Private, loopback, reserved and malformed values give ``None``."""
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None
    address = network.network_address
    return str(address) if address.is_global else None


def location_from_record(record: object) -> IpLocation | None:
    """Read a City record (DB-IP Lite and MaxMind share the layout)."""
    if not isinstance(record, Mapping):
        return None
    location = record.get("location")
    if not isinstance(location, Mapping):
        return None
    lat, lng = _number(location.get("latitude")), _number(location.get("longitude"))
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    city = record.get("city")
    city_names = city.get("names") if isinstance(city, Mapping) else None
    country = record.get("country")
    country = country if isinstance(country, Mapping) else {}
    names = country.get("names")
    return IpLocation(
        lat=lat,
        lng=lng,
        city=_text(city_names.get("en")) if isinstance(city_names, Mapping) else None,
        country_code=_text(country.get("iso_code")),
        country_names={
            str(tag): str(name)
            for tag, name in (names.items() if isinstance(names, Mapping) else ())
            if isinstance(name, str) and name.strip()
        },
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


class DbIpGeolocator:
    """Reads a City database in MMDB format (memory-mapped; lookups take microseconds)."""

    def __init__(self, path: Path) -> None:
        self._reader = maxminddb.open_database(str(path))

    def locate(self, address: str) -> IpLocation | None:
        public = public_address(address)
        if public is None:
            return None
        try:
            record = self._reader.get(public)
        except ValueError:
            return None
        return location_from_record(record)

    def close(self) -> None:
        self._reader.close()


def open_geolocator(path: Path | None) -> IpGeolocator:
    """The configured database, or ``NoIpGeolocation`` when it is unset or unreadable (the app
    then asks the traveller to choose a city)."""
    if path is None:
        return NoIpGeolocation()
    try:
        return DbIpGeolocator(path)
    except (OSError, RuntimeError, ValueError) as exc:  # InvalidDatabaseError is a RuntimeError
        logger.warning("ip geolocation database unavailable", extra={"reason": type(exc).__name__})
        return NoIpGeolocation()
