"""Approximate location from the IP address (LOC-010, ADR-0030): parsing, privacy and fallbacks."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.modules.location import fetch_ip_database, ip_geolocation
from app.modules.location.fetch_ip_database import candidate_months
from app.modules.location.ip_geolocation import (
    DbIpGeolocator,
    IpLocation,
    NoIpGeolocation,
    location_from_record,
    open_geolocator,
    public_address,
)

pytestmark = pytest.mark.req("LOC-010")

HELSINKI_RECORD: dict[str, Any] = {
    "city": {"names": {"en": "Helsinki"}},
    "country": {
        "iso_code": "FI",
        "names": {"en": "Finland", "de": "Finnland", "pt-BR": "Finlândia", "fr": "Finlande"},
    },
    "location": {"latitude": 60.1699, "longitude": 24.9384},
    "subdivisions": [{"names": {"en": "Uusimaa"}}],
}


def test_only_public_addresses_are_looked_up() -> None:
    assert public_address("81.2.69.142") == "81.2.69.142"
    assert public_address(" 8.8.8.8 ") == "8.8.8.8"
    # client_ip() reports IPv6 per /64; the network's first address stands for it.
    assert public_address("2a00:1450:4001:80b::/64") == "2a00:1450:4001:80b::"
    for private in ("127.0.0.1", "10.1.2.3", "192.168.0.10", "::1", "fd00::/64", "100.64.0.1"):
        assert public_address(private) is None, private
    for garbage in ("unknown", "", "testclient", "1.2.3"):
        assert public_address(garbage) is None, garbage


def test_a_city_record_is_read() -> None:
    found = location_from_record(HELSINKI_RECORD)
    assert found is not None
    assert (found.lat, found.lng) == (60.1699, 24.9384)
    assert found.city == "Helsinki"
    assert found.country_code == "FI"
    assert found.country_name(["de"]) == "Finnland"
    assert found.country_name(["pt-BR", "en"]) == "Finlândia"
    assert found.country_name(["fr-CA"]) == "Finlande"  # falls back to the base language
    assert found.country_name(["es"]) == "Finland"  # then English


def test_incomplete_or_odd_records_are_unknown() -> None:
    assert location_from_record(None) is None
    assert location_from_record({"country": {"iso_code": "FI"}}) is None
    assert location_from_record({"location": {"latitude": "60", "longitude": 24.9}}) is None
    assert location_from_record({"location": {"latitude": True, "longitude": 24.9}}) is None
    assert location_from_record({"location": {"latitude": 95.0, "longitude": 24.9}}) is None
    only_country = location_from_record({"location": {"latitude": 61.9, "longitude": 25.7}})
    assert only_country is not None
    assert only_country.city is None
    assert only_country.country_code is None
    assert only_country.country_name(["en"]) is None


@pytest.mark.security
def test_a_location_never_prints_its_point() -> None:
    found = IpLocation(lat=60.1699, lng=24.9384, city="Helsinki", country_code="FI")
    for text in (repr(found), str(found), f"{found}"):
        assert "60.1" not in text
        assert "24.9" not in text


class _Reader:
    def __init__(self, records: dict[str, Any]) -> None:
        self.records = records
        self.asked: list[str] = []

    def get(self, address: str) -> Any:
        self.asked.append(address)
        if address == "93.184.216.34":
            raise ValueError("not an address the reader accepts")
        return self.records.get(address)

    def close(self) -> None:
        pass


def test_the_database_is_asked_only_about_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader({"81.2.69.142": HELSINKI_RECORD})
    monkeypatch.setattr(ip_geolocation.maxminddb, "open_database", lambda _path: reader)
    geolocator = DbIpGeolocator(Path("city.mmdb"))
    found = geolocator.locate("81.2.69.142")
    assert found is not None
    assert found.city == "Helsinki"
    assert geolocator.locate("8.8.4.4") is None  # not in the database
    assert geolocator.locate("10.0.0.1") is None  # private: never looked up
    assert geolocator.locate("93.184.216.34") is None  # reader refuses it
    assert reader.asked == ["81.2.69.142", "8.8.4.4", "93.184.216.34"]


def test_a_missing_database_means_unknown_locations(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert isinstance(open_geolocator(None), NoIpGeolocation)
    with caplog.at_level(logging.WARNING):
        geolocator = open_geolocator(tmp_path / "missing.mmdb")
    assert isinstance(geolocator, NoIpGeolocation)
    assert geolocator.locate("81.2.69.142") is None
    assert "ip geolocation database unavailable" in caplog.text
    broken = tmp_path / "broken.mmdb"
    broken.write_bytes(b"not a database")
    assert isinstance(open_geolocator(broken), NoIpGeolocation)


def test_the_image_build_takes_this_month_or_last_months_file() -> None:
    assert candidate_months(date(2026, 11, 1)) == ["2026-11", "2026-10"]
    assert candidate_months(date(2026, 1, 15)) == ["2026-01", "2025-12"]


def test_the_image_build_falls_back_and_never_keeps_a_bad_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "geo" / "dbip-city-lite.mmdb"
    tried: list[str] = []

    def fetch(month: str, path: Path) -> None:
        tried.append(month)
        path.write_bytes(b"x")
        if len(tried) == 1:
            raise OSError("not published yet")

    monkeypatch.setattr(fetch_ip_database, "fetch", fetch)
    monkeypatch.setattr(fetch_ip_database, "validate", lambda _path: None)
    assert fetch_ip_database.main([str(target)]) == 0
    assert len(tried) == 2
    assert target.read_bytes() == b"x"
    assert not (target.parent / "dbip-city-lite.mmdb.partial").exists()

    def invalid(_path: Path) -> None:
        raise ValueError("unexpected database type")

    target.unlink()
    monkeypatch.setattr(fetch_ip_database, "validate", invalid)
    assert fetch_ip_database.main([str(target)]) == 1
    assert not target.exists()
    assert not (target.parent / "dbip-city-lite.mmdb.partial").exists()
