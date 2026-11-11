"""Download the DB-IP "IP to City Lite" database into the container image (ADR-0030).

``python -m app.modules.location.fetch_ip_database /srv/geo/dbip-city-lite.mmdb`` fetches this
month's file (or last month's, early in a month before it is published), checks that it opens as a
City database and moves it into place. The data is CC BY 4.0 (https://db-ip.com); the apps show
the credit. Exits with 1 when nothing could be fetched: the image is then built without it and the
API answers ``location_unresolvable`` until the next build.
"""

from __future__ import annotations

import argparse
import gzip
import sys
import urllib.request
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import maxminddb

URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
USER_AGENT = "TravelBuddyImageBuild/1.0"
# The City Lite file is about 130 MB unpacked; refuse anything far larger.
MAX_BYTES = 512 * 1024 * 1024
CHUNK = 1024 * 1024


def candidate_months(today: date) -> list[str]:
    """This month first, then last month."""
    first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    return [first.strftime("%Y-%m"), previous.strftime("%Y-%m")]


def fetch(month: str, target: Path) -> None:
    url = URL.format(month=month)  # a fixed https URL
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with (
        urllib.request.urlopen(request, timeout=300) as response,  # noqa: S310
        gzip.GzipFile(fileobj=response) as unpacked,
        target.open("wb") as out,
    ):
        written = 0
        while chunk := unpacked.read(CHUNK):
            written += len(chunk)
            if written > MAX_BYTES:
                raise ValueError("the download is larger than a City Lite database")
            out.write(chunk)


def validate(path: Path) -> None:
    with maxminddb.open_database(str(path)) as reader:
        kind = reader.metadata().database_type
    if "City" not in kind:
        raise ValueError(f"unexpected database type {kind!r}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the DB-IP City Lite database")
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    target: Path = args.target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    for month in candidate_months(datetime.now(tz=UTC).date()):
        try:
            fetch(month, partial)
            validate(partial)
        except (OSError, RuntimeError, ValueError, EOFError) as exc:
            sys.stderr.write(f"dbip-city-lite-{month}: {type(exc).__name__}: {exc}\n")
            partial.unlink(missing_ok=True)
            continue
        partial.replace(target)
        sys.stdout.write(f"dbip-city-lite-{month} -> {target}\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
