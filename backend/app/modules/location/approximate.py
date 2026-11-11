"""``GET /v1/users/me/approximate-location``: where the Companions map starts (LOC-010, ADR-0030).

The caller's IP address is looked up in a local database, rounded to about a kilometre, matched to
a covered city with the same point-to-destination resolution as a device fix, and then discarded.
The answer is only ever about the caller and only says "around this city". It changes nothing:
the traveller still presses Search to become discoverable there (LOC-004).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.modules.destinations import service as destinations
from app.modules.destinations.schemas import Destination, GeoPoint
from app.modules.location.ip_geolocation import IpGeolocator, IpLocation
from app.modules.location.schemas import ApproximateLocation

# 0.01 degrees is about 1.1 km: no finer than the city-level points the database holds.
ROUNDING_DIGITS = 2


class ApproximateLocationService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], geolocator: IpGeolocator
    ) -> None:
        self._sessionmaker = sessionmaker
        self._geolocator = geolocator

    async def locate(self, address: str, *, preferences: Sequence[str]) -> ApproximateLocation:
        found = self._geolocator.locate(address)
        if found is None:
            raise AppError(
                ErrorCode.LOCATION_UNRESOLVABLE,
                "We can't tell your area from your connection. Choose a city instead.",
            )
        lat, lng = round(found.lat, ROUNDING_DIGITS), round(found.lng, ROUNDING_DIGITS)
        async with self._sessionmaker() as session:
            city = await _covered_city(session, lat, lng, preferences)
        if city is not None:
            return ApproximateLocation(
                source="ip",
                precision="city",
                label=", ".join(part for part in (city.name, city.country_name) if part),
                center=city.centroid,
                destination=city,
            )
        return ApproximateLocation(
            source="ip",
            precision="city" if found.city else "country",
            label=_label(found, preferences),
            center=GeoPoint(lat=lat, lng=lng),
            destination=None,
        )


async def _covered_city(
    session: AsyncSession, lat: float, lng: float, preferences: Sequence[str]
) -> Destination | None:
    """The catalog city around the point. An address never places anyone in a neighbourhood, and
    a country alone is not somewhere to meet."""
    resolved = await destinations.resolve_point(session, lat, lng)
    if resolved is None:
        return None
    city = await destinations.city_of(session, resolved)
    if await destinations.kind_of(session, city) != "city":
        return None
    return await destinations.detail_by_id(session, city, preferences)


def _label(found: IpLocation, preferences: Sequence[str]) -> str:
    parts = (found.city, found.country_name(preferences) or found.country_code)
    return ", ".join(part for part in parts if part)
