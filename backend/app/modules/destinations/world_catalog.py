"""World gazetteer: every town of 5,000+ people and well-known tourist places (ADR-0035).

Two idempotent steps:

* ``build`` (development only) turns open data into two compact files next to the launch catalog:
  ``seed/world_cities.jsonl.gz`` from the GeoNames dumps (CC BY 4.0) and
  ``seed/world_attractions.jsonl.gz`` from Wikidata answers (CC0), both downloaded beforehand
  (``queries DIR`` writes the SPARQL to fetch)::

      python -m app.modules.destinations.world_catalog build --geonames DIR --wikidata DIR

* ``load`` upserts them: countries by ISO code, towns by GeoNames id (launch cities keep their
  editorial rows and only gain population and region), attractions as places of the town they
  belong to. Gazetteer destinations are searchable, resolvable and postable but stay out of the
  directory and the sitemap (``in_directory`` false) until an editor lists them::

      python -m app.modules.destinations.world_catalog load

Only public data about places is involved; no user data is read or written.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import math
import re
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

SEED_DIR: Final = Path(__file__).parent / "seed"
CITIES_FILE: Final = SEED_DIR / "world_cities.jsonl.gz"
ATTRACTIONS_FILE: Final = SEED_DIR / "world_attractions.jsonl.gz"
LAUNCH_FILE: Final = SEED_DIR / "launch_destinations.json"
# Country names in the app languages from Unicode CLDR (made with Node's ICU, see ADR-0035).
COUNTRY_NAMES_FILE: Final = SEED_DIR / "country_names.json"

GEONAMES_PROVIDER: Final = "geonames"
GEONAMES_LICENSE: Final = "CC-BY-4.0"
GEONAMES_ATTRIBUTION: Final = "GeoNames"
GEONAMES_URL: Final = "https://www.geonames.org/"
WIKIDATA_PROVIDER: Final = "wikidata"
WIKIDATA_LICENSE: Final = "CC0-1.0"
WIKIDATA_ATTRIBUTION: Final = "Wikidata"
WIKIDATA_URL: Final = "https://www.wikidata.org/"

# Populated places only: sections of cities, abandoned or historical places are left out.
TOWN_FEATURE_CODES: Final = frozenset(
    {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLG", "PPLS", "PPLL", "PPLF"}
)
# GeoNames language -> app locale.
LANGUAGES: Final[Mapping[str, str]] = {
    "en": "en",
    "es": "es",
    "pt": "pt-BR",
    "fr": "fr",
    "de": "de",
}
MAX_ALT_NAMES: Final = 6

# The app's continents split GeoNames' Asia and North America (docs/04).
_MIDDLE_EAST: Final = frozenset(
    {"AE", "BH", "IL", "IQ", "IR", "JO", "KW", "LB", "OM", "PS", "QA", "SA", "SY", "YE"}
)
_CENTRAL_AMERICA_CARIBBEAN: Final = frozenset(
    {
        *("BZ", "CR", "GT", "HN", "NI", "PA", "SV"),
        *("AG", "AI", "AW", "BB", "BL", "BQ", "BS", "CU", "CW", "DM", "DO", "GD", "GP", "HT"),
        *("JM", "KN", "KY", "LC", "MF", "MQ", "MS", "PR", "SX", "TC", "TT", "VC", "VG", "VI"),
    }
)
_CONTINENTS: Final[Mapping[str, str]] = {
    "AF": "africa",
    "AS": "asia",
    "EU": "europe",
    "NA": "north_america",
    "OC": "oceania",
    "SA": "south_america",
}


def continent_for(country_code: str, geonames_continent: str) -> str | None:
    """The app continent of a country, or ``None`` (Antarctica is not a destination)."""
    if country_code in _MIDDLE_EAST:
        return "middle_east"
    if country_code in _CENTRAL_AMERICA_CARIBBEAN:
        return "central_america_caribbean"
    return _CONTINENTS.get(geonames_continent)


def slugify(text: str) -> str:
    """``"São Paulo"`` -> ``"sao-paulo"`` (ASCII path segment, ``SEGMENT_PATTERN``)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def fold(text: str) -> str:
    """Accent- and case-insensitive form for comparing names."""
    return slugify(text).replace("-", " ")


# ─────────────────────────────── GeoNames parsing ───────────────────────────────


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    name: str
    continent: str
    geonames_id: int
    capital: str
    population: int


@dataclass(slots=True)
class Town:
    geonames_id: int
    name: str
    ascii_name: str
    lat: float
    lng: float
    country_code: str
    admin1: str
    population: int
    time_zone: str
    region: str | None = None
    admin2: str = ""
    feature_code: str = "PPL"
    names: dict[str, str] = field(default_factory=dict)
    alt_names: list[str] = field(default_factory=list)


def parse_countries(lines: Iterable[str]) -> dict[str, Country]:
    """``countryInfo.txt`` -> countries by ISO code (comment lines start with ``#``)."""
    countries: dict[str, Country] = {}
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 17 or not cols[16].isdigit():
            continue
        continent = continent_for(cols[0], cols[8])
        if continent is None:
            continue
        countries[cols[0]] = Country(
            code=cols[0],
            name=cols[4],
            continent=continent,
            geonames_id=int(cols[16]),
            capital=cols[5],
            population=int(cols[7] or 0),
        )
    return countries


def parse_regions(lines: Iterable[str]) -> dict[str, str]:
    """``admin1CodesASCII.txt`` -> ``{"BR.27": "São Paulo"}``."""
    regions: dict[str, str] = {}
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) >= 2 and cols[1]:
            regions[cols[0]] = cols[1]
    return regions


def parse_towns(
    lines: Iterable[str], countries: Mapping[str, Country], regions: Mapping[str, str]
) -> list[Town]:
    """A ``citiesNNNN.txt`` dump -> populated places of known countries, biggest first."""
    towns: list[Town] = []
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 19 or cols[7] not in TOWN_FEATURE_CODES or cols[8] not in countries:
            continue
        name = cols[1].strip()
        if not name or not slugify(name):
            continue
        towns.append(
            Town(
                geonames_id=int(cols[0]),
                name=name,
                ascii_name=cols[2].strip(),
                lat=round(float(cols[4]), 5),
                lng=round(float(cols[5]), 5),
                country_code=cols[8],
                admin1=cols[10],
                population=int(cols[14] or 0),
                time_zone=cols[17],
                region=regions.get(f"{cols[8]}.{cols[10]}"),
                admin2=cols[11],
                feature_code=cols[7],
            )
        )
    towns.sort(key=lambda t: (-t.population, t.geonames_id))
    return without_districts(towns)


# Countries whose GeoNames second-level division is the municipality (municipio, concelho): a
# populated place in the same municipality as its seat is a district of that town, like Barra
# da Tijuca in Rio de Janeiro, not a destination of its own.
MUNICIPALITY_COUNTRIES: Final = frozenset({"BR", "PT"})
_SEATS: Final = frozenset({"PPLC", "PPLA", "PPLA2"})
DISTRICT_MAX_KM: Final = 40.0


# Numbered city districts ("Paris 15 Vaugirard", "Lyon 03") belong to the city named before
# the number.
_NUMBERED_DISTRICT: Final = re.compile(r"^(.+?) \d{1,2}(?:er|e|eme|ème)?(?: |$)")


def without_districts(towns: Sequence[Town]) -> list[Town]:
    """``towns`` without the districts of a bigger town: places in the municipality of their
    seat (``MUNICIPALITY_COUNTRIES``) and numbered districts near the city they are named after."""
    seats: dict[tuple[str, str, str], Town] = {}
    by_name: dict[tuple[str, str], Town] = {}
    for town in towns:
        by_name.setdefault((town.country_code, fold(town.name)), town)  # biggest first
        if town.country_code in MUNICIPALITY_COUNTRIES and town.feature_code in _SEATS:
            seats.setdefault((town.country_code, town.admin1, town.admin2), town)
    kept: list[Town] = []
    for town in towns:
        seat = seats.get((town.country_code, town.admin1, town.admin2))
        numbered = _NUMBERED_DISTRICT.match(town.name)
        if numbered is not None:
            seat = seat or by_name.get((town.country_code, fold(numbered.group(1))))
        elif not town.admin2:
            seat = None
        if (
            seat is not None
            and seat is not town
            and (numbered is not None or town.feature_code not in _SEATS)
            and distance_km(town.lat, town.lng, seat.lat, seat.lng) <= DISTRICT_MAX_KM
        ):
            continue
        kept.append(town)
    return kept


@dataclass(slots=True)
class _Candidate:
    name: str
    preferred: bool
    short: bool

    def rank(self) -> tuple[bool, bool]:
        # Preferred first; a full name ("Rio de Janeiro") over a short one ("Rio").
        return (self.preferred, not self.short)


def _is_acronym(name: str) -> bool:
    return len(name) <= 5 and " " not in name and name.replace(".", "").isupper()


def collect_names(
    lines: Iterable[str], ids: set[int]
) -> tuple[dict[int, dict[str, str]], dict[int, list[str]]]:
    """``alternateNamesV2.txt`` -> (localized names by locale, abbreviations) for ``ids``.

    Per language the preferred name wins, then a full name over a short one, then the first one
    listed; acronyms are kept as abbreviations, colloquial and historic names are ignored."""
    best: dict[tuple[int, str], _Candidate] = {}
    abbreviations: dict[int, list[str]] = defaultdict(list)
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 8:
            continue
        language = cols[2]
        if language not in LANGUAGES and language != "abbr":
            continue
        try:
            geonames_id = int(cols[1])
        except ValueError:
            continue
        if geonames_id not in ids or cols[6] == "1" or cols[7] == "1":
            continue
        name = cols[3].strip()
        if not name:
            continue
        if language == "abbr" or (_is_acronym(name) and len(name) > 1):
            if len(abbreviations[geonames_id]) < 3 and name not in abbreviations[geonames_id]:
                abbreviations[geonames_id].append(name)
            continue
        candidate = _Candidate(name, cols[4] == "1", cols[5] == "1")
        key = (geonames_id, LANGUAGES[language])
        current = best.get(key)
        if current is None or candidate.rank() > current.rank():
            best[key] = candidate
    names: dict[int, dict[str, str]] = defaultdict(dict)
    for (geonames_id, locale), candidate in best.items():
        names[geonames_id][locale] = candidate.name
    return dict(names), dict(abbreviations)


# ─────────────────────────────── paths ───────────────────────────────


def assign_segments(
    towns: Sequence[Town],
    *,
    reserved_segments: Mapping[str, set[str]],
    reserved_slugs: set[str],
    matched: Mapping[int, str],
) -> dict[int, str]:
    """A unique path segment under its country for every town not matched to a launch city.

    The biggest town keeps the plain name; namesakes get their region, then their GeoNames id
    (``sao-paulo``, ``bom-jesus-piaui``, ``bom-jesus-123``). ``towns`` must be biggest first, so
    re-running the build gives the same segments."""
    used: dict[str, set[str]] = defaultdict(set)
    for country, reserved in reserved_segments.items():
        used[country] |= reserved
    slugs = set(reserved_slugs)
    segments: dict[int, str] = {}
    for town in towns:
        if town.geonames_id in matched:
            continue
        base = slugify(town.name)
        options = [base]
        if town.region and slugify(town.region):
            options.append(f"{base}-{slugify(town.region)}")
        options.append(f"{base}-{town.geonames_id}")
        for option in options:
            slug = f"{option}-{town.country_code.lower()}"
            if option not in used[town.country_code] and slug not in slugs:
                used[town.country_code].add(option)
                slugs.add(slug)
                segments[town.geonames_id] = option
                break
    return segments


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def match_launch_cities(
    launch: Sequence[Mapping[str, Any]], towns: Sequence[Town]
) -> dict[int, str]:
    """GeoNames id -> launch path for the launch cities: a namesake within 30 km, else the
    biggest town within 15 km of the launch centroid."""
    by_country: dict[str, list[Town]] = defaultdict(list)
    for town in towns:
        by_country[town.country_code].append(town)
    matched: dict[int, str] = {}
    for entry in launch:
        if entry["kind"] != "city":
            continue
        names = {fold(n) for n in entry["names"].values()}
        names |= {fold(n) for alts in entry.get("alt_names", {}).values() for n in alts}
        lat, lng = entry["centroid"]["lat"], entry["centroid"]["lng"]
        nearby = [
            (t, distance_km(lat, lng, t.lat, t.lng))
            for t in by_country[entry["country_code"]]
            if t.geonames_id not in matched
        ]
        namesakes = [
            t for t, d in nearby if d <= 30 and ({fold(t.name), fold(t.ascii_name)} & names)
        ]
        close = [t for t, d in nearby if d <= 15]
        pick = next(iter(namesakes or close), None)  # towns are biggest first
        if pick is not None:
            matched[pick.geonames_id] = entry["path"]
    return matched


def town_reach_km(population: int | None) -> float:
    """About half the radius of a town of this size (5,000 people per km², capped at 15 km)."""
    if not population or population <= 0:
        return 0.0
    return min(15.0, 0.5 * math.sqrt(population / (math.pi * 5000.0)))


def belonging(distance: float, reach: float) -> float:
    """How far a point is from a town relative to its size; the smallest value wins. A big city
    keeps its outskirts from a small neighbour whose centre is closer, while a separate town
    across a bay (Niterói and Rio de Janeiro) keeps its own centre."""
    return distance / (reach + 1.0)


# ─────────────────────────────── build ───────────────────────────────


def _zip_lines(path: Path, member: str) -> Iterator[str]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as raw:
        yield from io.TextIOWrapper(raw, encoding="utf-8")


def _localized(default: str, names: Mapping[str, str]) -> dict[str, str]:
    return {locale: name for locale, name in sorted(names.items()) if name != default}


def build_city_records(
    *,
    countries: Mapping[str, Country],
    towns: Sequence[Town],
    names: Mapping[int, Mapping[str, str]],
    abbreviations: Mapping[int, Sequence[str]],
    launch: Sequence[Mapping[str, Any]],
    country_names: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Country and town records for ``world_cities.jsonl.gz`` (countries first)."""
    launch_countries = {e["country_code"]: e["path"] for e in launch if e["kind"] == "country"}
    reserved_segments: dict[str, set[str]] = defaultdict(set)
    for entry in launch:
        segments = entry["path"].split("/")
        if entry["kind"] != "country" and len(segments) == 2:
            reserved_segments[entry["country_code"]].add(segments[1])
    reserved_slugs = {_launch_slug(e) for e in launch}
    matched = match_launch_cities(launch, towns)
    segments = assign_segments(
        towns,
        reserved_segments=reserved_segments,
        reserved_slugs=reserved_slugs,
        matched=matched,
    )
    capitals: dict[str, Town] = {}
    biggest: dict[str, Town] = {}
    for town in towns:
        biggest.setdefault(town.country_code, town)
        country = countries[town.country_code]
        if town.country_code not in capitals and fold(town.name) == fold(country.capital):
            capitals[town.country_code] = town
    records: list[dict[str, Any]] = []
    used_country_segments = set(launch_countries.values())
    for code in sorted(countries):
        country = countries[code]
        anchor = capitals.get(code) or biggest.get(code)
        if anchor is None:
            continue  # no town of 5,000+ people: nothing to resolve or search there
        cldr = country_names.get(code, {})
        default = cldr.get("en") or country.name
        record: dict[str, Any] = {
            "type": "country",
            "code": code,
            "geonames_id": country.geonames_id,
            "name": default,
            "names": _localized(default, cldr or names.get(country.geonames_id, {})),
            "continent": country.continent,
            "lat": anchor.lat,
            "lng": anchor.lng,
            "time_zone": anchor.time_zone,
            "population": country.population,
        }
        if code in launch_countries:
            record["launch_path"] = launch_countries[code]
        else:
            segment = slugify(default)
            if segment in used_country_segments:
                segment = f"{segment}-{code.lower()}"
            used_country_segments.add(segment)
            record["segment"] = segment
        records.append(record)
    for town in towns:
        localized = _localized(town.name, names.get(town.geonames_id, {}))
        alts = [town.ascii_name] if town.ascii_name and town.ascii_name != town.name else []
        alts += [a for a in abbreviations.get(town.geonames_id, []) if a not in alts]
        record = {
            "type": "town",
            "code": town.country_code,
            "geonames_id": town.geonames_id,
            "name": town.name,
            "names": localized,
            "alt": alts[:MAX_ALT_NAMES],
            "region": town.region,
            "lat": town.lat,
            "lng": town.lng,
            "time_zone": town.time_zone,
            "population": town.population,
        }
        if town.geonames_id in matched:
            record["launch_path"] = matched[town.geonames_id]
        elif town.geonames_id in segments:
            record["segment"] = segments[town.geonames_id]
        else:
            continue
        records.append(record)
    return records


def _launch_slug(entry: Mapping[str, Any]) -> str:
    from app.modules.destinations.seeding import slug_for

    return slug_for(entry["path"], entry["country_code"], entry["kind"])


def write_records(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    # No name or time in the header: the same data gives the same bytes (no diff on rebuild).
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=9) as out,
    ):
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode())
            out.write(b"\n")
            count += 1
    return count


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            if line.strip():
                yield json.loads(line)


def build_cities(geonames_dir: Path, out: Path = CITIES_FILE) -> int:
    countries = parse_countries(
        (geonames_dir / "countryInfo.txt").read_text(encoding="utf-8").splitlines()
    )
    regions = parse_regions(
        (geonames_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines()
    )
    towns = parse_towns(
        _zip_lines(geonames_dir / "cities5000.zip", "cities5000.txt"), countries, regions
    )
    ids = {t.geonames_id for t in towns} | {c.geonames_id for c in countries.values()}
    names, abbreviations = collect_names(
        _zip_lines(geonames_dir / "alternateNamesV2.zip", "alternateNamesV2.txt"), ids
    )
    launch = json.loads(LAUNCH_FILE.read_text(encoding="utf-8"))["destinations"]
    country_names = json.loads(COUNTRY_NAMES_FILE.read_text(encoding="utf-8"))["countries"]
    records = build_city_records(
        countries=countries,
        towns=towns,
        names=names,
        abbreviations=abbreviations,
        launch=launch,
        country_names=country_names,
    )
    return write_records(out, records)


# ─────────────────────────────── attractions (Wikidata) ───────────────────────────────

# (Wikidata class, minimum Wikipedia/Wikivoyage sitelinks, place category). Streets and roads are
# deliberately absent: search offers towns and places to visit, never addresses. ``heritage-Q9259``
# means "designated a UNESCO World Heritage Site" (P1435) rather than an instance of a class.
ATTRACTION_CLASSES: Final[tuple[tuple[str, int, str], ...]] = (
    ("heritage-Q9259", 3, "attraction"),  # designated World Heritage Site
    ("Q9259", 3, "attraction"),  # World Heritage Site
    ("Q570116", 4, "attraction"),  # tourist attraction
    ("Q2319498", 8, "attraction"),  # landmark
    ("Q4989906", 10, "attraction"),  # monument
    ("Q179700", 10, "attraction"),  # statue
    ("Q23413", 12, "attraction"),  # castle
    ("Q16560", 12, "attraction"),  # palace
    ("Q1785071", 12, "attraction"),  # fort
    ("Q2977", 12, "attraction"),  # cathedral
    ("Q163687", 12, "attraction"),  # basilica
    ("Q16970", 25, "attraction"),  # church building
    ("Q32815", 20, "attraction"),  # mosque
    ("Q44539", 12, "attraction"),  # temple
    ("Q842402", 10, "attraction"),  # Hindu temple
    ("Q5393308", 10, "attraction"),  # Buddhist temple
    ("Q12518", 15, "attraction"),  # tower
    ("Q11303", 25, "attraction"),  # skyscraper
    ("Q12280", 20, "attraction"),  # bridge
    ("Q174782", 15, "attraction"),  # town square
    ("Q43501", 10, "attraction"),  # zoo
    ("Q2281788", 8, "attraction"),  # public aquarium
    ("Q194195", 10, "attraction"),  # amusement park
    ("Q2416723", 10, "attraction"),  # theme park
    ("Q839954", 15, "attraction"),  # archaeological site
    ("Q109607", 15, "attraction"),  # ruins
    ("Q34038", 8, "attraction"),  # waterfall
    ("Q35509", 12, "attraction"),  # cave
    ("Q8502", 40, "viewpoint"),  # mountain
    ("Q6017969", 3, "viewpoint"),  # scenic viewpoint
    ("Q39715", 15, "attraction"),  # lighthouse
    ("Q483110", 30, "attraction"),  # stadium
    ("Q153562", 12, "attraction"),  # opera house
    ("Q33506", 10, "museum"),  # museum
    ("Q207694", 10, "museum"),  # art museum
    ("Q588140", 10, "museum"),  # science museum
    ("Q1007870", 10, "museum"),  # art gallery
    ("Q22698", 10, "park"),  # park
    ("Q22746", 10, "park"),  # urban park
    ("Q46169", 8, "park"),  # national park
    ("Q167346", 8, "park"),  # botanical garden
    ("Q1107656", 12, "park"),  # garden
    ("Q40080", 5, "beach"),  # beach
    ("Q330284", 8, "market"),  # marketplace
)
_LABEL_LANGUAGES: Final[Mapping[str, str]] = {
    "en": "en",
    "es": "es",
    "pt-br": "pt-BR",
    "pt": "pt-BR",
    "fr": "fr",
    "de": "de",
}


# Ruins are visited as ruins: a "dissolved or demolished" date doesn't remove them.
_RUIN_CLASSES: Final = frozenset({"heritage-Q9259", "Q9259", "Q839954", "Q109607"})
_HERITAGE_CLASSES: Final = frozenset({"heritage-Q9259", "Q9259"})


def attraction_query(wikidata_class: str, min_sitelinks: int) -> str:
    """SPARQL for one class: items with coordinates and enough sitelinks, still standing."""
    if wikidata_class.startswith("heritage-"):
        pattern = f"wdt:P1435 wd:{wikidata_class.removeprefix('heritage-')}"
    else:
        pattern = f"wdt:P31 wd:{wikidata_class}"
    standing = (
        "" if wikidata_class in _RUIN_CLASSES else "\n  FILTER NOT EXISTS { ?item wdt:P576 [] }"
    )
    if wikidata_class in _HERITAGE_CLASSES:
        # Whole historic towns and districts are World Heritage too; they are destinations.
        standing += (
            "\n  FILTER NOT EXISTS { ?item wdt:P31/wdt:P279* ?settlement ."
            " VALUES ?settlement { wd:Q486972 wd:Q123705 wd:Q56061 } }"
        )
    return f"""
SELECT ?item ?coord ?sl ?label ?lang WHERE {{
  ?item {pattern} ; wikibase:sitelinks ?sl ; wdt:P625 ?coord .
  FILTER(?sl >= {min_sitelinks}){standing}
  ?item rdfs:label ?label .
  BIND(LANG(?label) AS ?lang)
  FILTER(?lang IN ("en", "es", "pt", "pt-br", "fr", "de"))
}}"""


_POINT = re.compile(r"^Point\((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)$")


def parse_attraction_rows(
    bindings: Iterable[Mapping[str, Any]], category: str
) -> dict[str, dict[str, Any]]:
    """SPARQL JSON bindings -> attraction records by QID (Earth coordinates only)."""
    records: dict[str, dict[str, Any]] = {}
    for row in bindings:
        qid = str(row["item"]["value"]).rsplit("/", 1)[-1]
        match = _POINT.fullmatch(str(row["coord"]["value"]))
        if match is None:  # coordinates on another globe come with a URI prefix
            continue
        lng, lat = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        record = records.setdefault(
            qid,
            {
                "qid": qid,
                "category": category,
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "sitelinks": int(row["sl"]["value"]),
                "labels": {},
            },
        )
        locale = _LABEL_LANGUAGES.get(str(row["lang"]["value"]))
        label = str(row["label"]["value"]).strip()
        if locale and label and (locale not in record["labels"] or row["lang"]["value"] == "pt-br"):
            record["labels"][locale] = label[:200]
    return records


def attraction_records(found: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Final records: a default name (English first), localized names that differ from it,
    most notable first."""
    out: list[dict[str, Any]] = []
    for qid, record in found.items():
        labels: Mapping[str, str] = record["labels"]
        default = next((labels[k] for k in ("en", "pt-BR", "es", "fr", "de") if k in labels), None)
        if default is None:
            continue
        out.append(
            {
                "qid": qid,
                "name": default,
                "names": _localized(default, labels),
                "category": record["category"],
                "lat": record["lat"],
                "lng": record["lng"],
                "sitelinks": record["sitelinks"],
            }
        )
    out.sort(key=lambda r: (-r["sitelinks"], r["qid"]))
    return out


def write_queries(folder: Path) -> list[Path]:
    """One ``<class>.rq`` SPARQL file per attraction class. Fetch each into ``<class>.json``
    (``Accept: application/sparql-results+json``) from https://query.wikidata.org/sparql, e.g.
    with curl; the public endpoint refuses some HTTP client libraries."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for wikidata_class, min_sitelinks, _category in ATTRACTION_CLASSES:
        path = folder / f"{wikidata_class}.rq"
        path.write_text(attraction_query(wikidata_class, min_sitelinks), encoding="utf-8")
        written.append(path)
    return written


def build_attractions(wikidata_dir: Path, out: Path = ATTRACTIONS_FILE) -> int:
    """``world_attractions.jsonl.gz`` from the fetched ``<class>.json`` answers."""
    found: dict[str, dict[str, Any]] = {}
    for wikidata_class, _min_sitelinks, category in ATTRACTION_CLASSES:
        answer = json.loads((wikidata_dir / f"{wikidata_class}.json").read_text(encoding="utf-8"))
        rows = parse_attraction_rows(answer["results"]["bindings"], category)
        for qid, record in rows.items():
            found.setdefault(qid, record)  # the first (more specific) class wins
    return write_records(out, attraction_records(found))


# ─────────────────────────────── CLI ───────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="World gazetteer (ADR-0035)")
    commands = parser.add_subparsers(dest="command", required=True)
    queries = commands.add_parser("queries", help="write the Wikidata SPARQL queries")
    queries.add_argument("folder", type=Path)
    build = commands.add_parser("build", help="regenerate the seed files from open data")
    build.add_argument("--geonames", type=Path, help="folder with the GeoNames dumps")
    build.add_argument("--wikidata", type=Path, help="folder with the fetched <class>.json")
    commands.add_parser("load", help="upsert the seed files into the catalog")
    args = parser.parse_args()
    if args.command == "queries":
        print(f"{len(write_queries(args.folder))} queries")  # noqa: T201 - CLI output
    elif args.command == "build":
        if args.geonames:
            print(f"cities: {build_cities(args.geonames)} records")  # noqa: T201 - CLI output
        if args.wikidata:
            count = build_attractions(args.wikidata)
            print(f"attractions: {count} records")  # noqa: T201 - CLI output
    else:
        from app.modules.destinations.world_loader import run_load

        asyncio.run(run_load())


if __name__ == "__main__":
    main()
