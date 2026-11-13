"""World gazetteer build rules (ADR-0035): parsing, districts, names, paths, attractions."""

from __future__ import annotations

import gzip
import json
import uuid
from pathlib import Path

import pytest

from app.modules.destinations import world_catalog as wc
from app.modules.destinations.service import (
    Covering,
    NearestTown,
    _choose,
    destination_prominence,
    like_escape,
    place_prominence,
)
from app.modules.destinations.world_loader import TownIndex, TownPoint, town_popularity

pytestmark = pytest.mark.req("LOC-005", "DEST-001")


def _country_line(code: str, name: str, continent: str, geonames_id: int, capital: str) -> str:
    cols = [code, "XXX", "000", "", name, capital, "1000", "5000000", continent]
    cols += ["", "", "", "", "", "", "", str(geonames_id), "", ""]
    return "\t".join(cols)


def _town_line(
    geonames_id: int,
    name: str,
    lat: float,
    lng: float,
    code: str,
    population: int,
    *,
    feature: str = "PPL",
    admin1: str = "27",
    admin2: str = "",
    ascii_name: str | None = None,
) -> str:
    cols = [str(geonames_id), name, ascii_name or name, "", str(lat), str(lng), "P", feature, code]
    cols += ["", admin1, admin2, "", "", str(population), "", "", "America/Sao_Paulo", "2026-01-01"]
    return "\t".join(cols)


COUNTRIES = wc.parse_countries(
    [
        "# ISO\tISO3\t...",
        _country_line("BR", "Brazil", "SA", 3469034, "Brasilia"),
        _country_line("PT", "Portugal", "EU", 2264397, "Lisbon"),
        _country_line("DO", "Dominican Republic", "NA", 3508796, "Santo Domingo"),
        _country_line("AE", "United Arab Emirates", "AS", 290557, "Abu Dhabi"),
        _country_line("AQ", "Antarctica", "AN", 6697173, ""),
        _country_line("FR", "France", "EU", 3017382, "Paris"),
    ]
)
REGIONS = wc.parse_regions(["BR.27\tSão Paulo\tSao Paulo\t3448433", "BR.21\tRio de Janeiro\tx\t1"])


def test_countries_get_the_app_continents() -> None:
    assert COUNTRIES["BR"].continent == "south_america"
    assert COUNTRIES["DO"].continent == "central_america_caribbean"
    assert COUNTRIES["AE"].continent == "middle_east"
    assert "AQ" not in COUNTRIES  # Antarctica is not a destination
    assert wc.continent_for("JP", "AS") == "asia"


def test_slugs_and_folding_drop_accents() -> None:
    assert wc.slugify("São Paulo") == "sao-paulo"
    assert wc.slugify("Côte d\u2019Ivoire") == "cote-divoire"
    assert wc.fold("Niterói") == wc.fold("NITEROI") == "niteroi"


def test_only_populated_places_of_known_countries_biggest_first() -> None:
    towns = wc.parse_towns(
        [
            _town_line(1, "Campinas", -22.9, -47.06, "BR", 1_000_000, feature="PPLA2"),
            _town_line(2, "São Paulo", -23.55, -46.63, "BR", 12_400_000, feature="PPLA"),
            _town_line(3, "Vila Mariana", -23.59, -46.63, "BR", 300_000, feature="PPLX"),
            _town_line(4, "Somewhere", 1.0, 1.0, "ZZ", 50_000),
        ],
        COUNTRIES,
        REGIONS,
    )
    assert [t.name for t in towns] == ["São Paulo", "Campinas"]
    assert towns[0].region == "São Paulo"


def test_districts_of_a_municipality_and_numbered_districts_are_dropped() -> None:
    rio = {"admin1": "21", "admin2": "3304557"}
    paris = {"admin1": "11", "admin2": "75"}
    towns = wc.parse_towns(
        [
            _town_line(10, "Rio de Janeiro", -22.9, -43.2, "BR", 6_700_000, feature="PPLA", **rio),
            # Barra da Tijuca is in the municipality of Rio: a district, not a town.
            _town_line(11, "Barra da Tijuca", -23.0, -43.36, "BR", 135_000, **rio),
            # Niterói is its own municipality.
            _town_line(
                12, "Niterói", -22.88, -43.1, "BR", 480_000, feature="PPLA2", admin2="3303302"
            ),
            _town_line(20, "Paris", 48.85, 2.35, "FR", 2_100_000, feature="PPLC", **paris),
            _town_line(21, "Paris 15 Vaugirard", 48.84, 2.29, "FR", 230_000, **paris),
            _town_line(22, "Lyon", 45.75, 4.85, "FR", 520_000, feature="PPLA", admin2="69"),
        ],
        COUNTRIES,
        REGIONS,
    )
    assert {t.name for t in towns} == {"Rio de Janeiro", "Niterói", "Paris", "Lyon"}


def test_localized_names_prefer_preferred_full_names() -> None:
    lines = [
        # id, geonameid, lang, name, preferred, short, colloquial, historic
        "1\t2635167\ten\tUnited Kingdom\t1\t1\t\t",
        "2\t2635167\ten\tUnited Kingdom of Great Britain and Northern Ireland\t\t\t\t",
        "3\t2750405\tes\tHolanda\t1\t1\t\t",
        "4\t2750405\tes\tPaíses Bajos\t1\t\t\t",
        "5\t2750405\tpt\tHolanda\t\t1\t1\t",
        "6\t6252001\tpt\tEUA\t1\t\t\t",
        "7\t5128581\tabbr\tNYC\t\t\t\t",
        "8\t5128581\tde\tNeu-Amsterdam\t\t\t\t1",
        "9\t999\tes\tIgnored\t1\t\t\t",
    ]
    names, abbreviations = wc.collect_names(lines, {2635167, 2750405, 6252001, 5128581})
    assert names[2635167]["en"] == "United Kingdom"
    assert names[2750405]["es"] == "Países Bajos"  # a full name over a short one
    assert "pt-BR" not in names[2750405]  # colloquial
    assert "pt-BR" not in names.get(6252001, {})  # an acronym is no display name
    assert abbreviations[6252001] == ["EUA"]
    assert abbreviations[5128581] == ["NYC"]
    assert 5128581 not in names  # historic names are ignored


def _town(
    geonames_id: int, name: str, lat: float, lng: float, population: int, region: str | None
) -> wc.Town:
    return wc.Town(geonames_id, name, name, lat, lng, "BR", "", population, "", region)


def test_namesakes_get_their_region_then_their_id() -> None:
    towns = [
        wc.Town(1, "Bom Jesus", "Bom Jesus", -9.0, -44.3, "BR", "20", 25_000, "", "Piauí"),
        wc.Town(
            2, "Bom Jesus", "Bom Jesus", -28.6, -50.4, "BR", "23", 11_000, "", "Rio Grande do Sul"
        ),
        wc.Town(
            3, "Bom Jesus", "Bom Jesus", -28.7, -50.5, "BR", "23", 9_000, "", "Rio Grande do Sul"
        ),
        wc.Town(4, "Rio de Janeiro", "Rio de Janeiro", -22.9, -43.2, "BR", "21", 6_700_000, ""),
        wc.Town(
            5, "Copacabana", "Copacabana", -22.97, -43.18, "BR", "21", 8_000, "", "Rio de Janeiro"
        ),
    ]
    segments = wc.assign_segments(
        towns,
        reserved_segments={"BR": {"rio-de-janeiro"}},
        reserved_slugs={"copacabana-br"},
        matched={4: "brazil/rio-de-janeiro"},
    )
    assert segments == {
        1: "bom-jesus",
        2: "bom-jesus-rio-grande-do-sul",
        3: "bom-jesus-3",
        5: "copacabana-rio-de-janeiro",  # the plain slug is taken
    }


def test_launch_cities_match_their_namesake_nearby() -> None:
    launch = [
        {
            "path": "portugal/lisbon",
            "kind": "city",
            "country_code": "PT",
            "centroid": {"lat": 38.7223, "lng": -9.1393},
            "names": {"en": "Lisbon", "pt-BR": "Lisboa"},
        }
    ]
    towns = [
        wc.Town(7, "Amadora", "Amadora", 38.75, -9.23, "PT", "14", 175_000, ""),
        wc.Town(8, "Lisbon", "Lisbon", 38.725, -9.15, "PT", "14", 517_000, ""),
    ]
    assert wc.match_launch_cities(launch, towns) == {8: "portugal/lisbon"}


def test_a_big_city_keeps_its_outskirts_and_a_town_across_the_bay_keeps_its_centre() -> None:
    rio, niteroi = wc.town_reach_km(6_700_000), wc.town_reach_km(480_000)
    assert wc.town_reach_km(None) == 0.0
    assert wc.town_reach_km(50_000_000) == 15.0
    # Central Niterói: 1 km from its centre, 8 km from Rio's.
    assert wc.belonging(1.0, niteroi) < wc.belonging(8.0, rio)
    # East São Paulo: 20 km from the centre of São Paulo, 12 km from Guarulhos'.
    sao_paulo, guarulhos = wc.town_reach_km(12_400_000), wc.town_reach_km(1_300_000)
    assert wc.belonging(20.0, sao_paulo) < wc.belonging(12.0, guarulhos)


def test_attraction_queries_keep_ruins_and_skip_towns_among_heritage_sites() -> None:
    museum = wc.attraction_query("Q33506", 10)
    assert "wdt:P31 wd:Q33506" in museum
    assert "wdt:P576" in museum  # demolished buildings are left out
    assert "FILTER(?sl >= 10)" in museum
    ruins = wc.attraction_query("Q839954", 15)
    assert "wdt:P576" not in ruins  # Machu Picchu was abandoned centuries ago
    heritage = wc.attraction_query("heritage-Q9259", 3)
    assert "wdt:P1435 wd:Q9259" in heritage
    assert "wd:Q486972" in heritage  # historic towns are destinations, not places
    assert not any(c in {"Q79007", "Q34442"} for c, _, _ in wc.ATTRACTION_CLASSES)  # no streets


def _binding(qid: str, coord: str, lang: str, label: str, sitelinks: int = 50) -> dict[str, object]:
    return {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "coord": {"value": coord},
        "sl": {"value": str(sitelinks)},
        "label": {"value": label},
        "lang": {"value": lang},
    }


def test_attraction_answers_become_localized_records() -> None:
    rows = wc.parse_attraction_rows(
        [
            _binding("Q79961", "Point(-43.21046 -22.95192)", "en", "Christ the Redeemer", 94),
            _binding("Q79961", "Point(-43.21046 -22.95192)", "pt", "Cristo Rei"),
            _binding("Q79961", "Point(-43.21046 -22.95192)", "pt-br", "Cristo Redentor"),
            _binding("Q1", "<http://www.wikidata.org/entity/Q405> Point(1 2)", "en", "Moon crater"),
            _binding("Q2", "Point(10 20)", "de", "Nur Deutsch", 5),
        ],
        "attraction",
    )
    assert set(rows) == {"Q79961", "Q2"}
    records = wc.attraction_records(rows)
    assert records[0] == {
        "qid": "Q79961",
        "name": "Christ the Redeemer",
        "names": {"pt-BR": "Cristo Redentor"},
        "category": "attraction",
        "lat": -22.95192,
        "lng": -43.21046,
        "sitelinks": 94,
    }
    assert records[1]["name"] == "Nur Deutsch"
    assert records[1]["names"] == {}


def test_city_records_reuse_launch_rows_and_name_new_countries_from_cldr() -> None:
    towns = [
        wc.Town(
            3451190,
            "Rio de Janeiro",
            "Rio de Janeiro",
            -22.9,
            -43.2,
            "BR",
            "21",
            6_700_000,
            "America/Sao_Paulo",
            "Rio de Janeiro",
        ),
        wc.Town(
            3448439,
            "São Paulo",
            "Sao Paulo",
            -23.55,
            -46.63,
            "BR",
            "27",
            12_400_000,
            "America/Sao_Paulo",
            "São Paulo",
        ),
        wc.Town(2267057, "Lisbon", "Lisbon", 38.72, -9.14, "PT", "14", 517_000, "Europe/Lisbon"),
    ]
    launch = [
        {"path": "brazil", "kind": "country", "country_code": "BR"},
        {
            "path": "brazil/rio-de-janeiro",
            "kind": "city",
            "country_code": "BR",
            "centroid": {"lat": -22.9068, "lng": -43.1729},
            "names": {"en": "Rio de Janeiro"},
        },
    ]
    records = wc.build_city_records(
        countries=COUNTRIES,
        towns=towns,
        names={3448439: {"en": "São Paulo", "fr": "São Paulo"}},
        abbreviations={3448439: ["SP"]},
        launch=launch,
        country_names={"PT": {"en": "Portugal", "pt-BR": "Portugal", "de": "Portugal"}},
    )
    by_name = {r["name"]: r for r in records}
    assert by_name["Brazil"]["launch_path"] == "brazil"
    assert by_name["Portugal"]["segment"] == "portugal"
    assert by_name["Portugal"]["names"] == {}
    assert "France" not in by_name  # no town of 5,000+ people in this sample
    assert by_name["Rio de Janeiro"]["launch_path"] == "brazil/rio-de-janeiro"
    sao_paulo = by_name["São Paulo"]
    assert sao_paulo["segment"] == "sao-paulo"
    assert sao_paulo["alt"] == ["Sao Paulo", "SP"]
    assert sao_paulo["names"] == {}  # same as the default name
    assert sao_paulo["region"] == "São Paulo"


def test_seed_files_are_byte_for_byte_reproducible(tmp_path: Path) -> None:
    records = [{"type": "town", "name": "Niterói", "n": 1}, {"type": "town", "name": "Rio"}]
    first, second = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    assert wc.write_records(first, records) == 2
    wc.write_records(second, records)
    assert first.read_bytes() == second.read_bytes()
    assert list(wc.read_records(first)) == records
    assert json.loads(gzip.decompress(first.read_bytes()).splitlines()[0])["name"] == "Niterói"


def test_the_shipped_seed_files_are_consistent() -> None:
    cities = list(wc.read_records(wc.CITIES_FILE))
    countries = {r["code"] for r in cities if r["type"] == "country"}
    towns = [r for r in cities if r["type"] == "town"]
    assert len(towns) > 60_000
    assert all(t["code"] in countries for t in towns)
    assert all(("segment" in t) != ("launch_path" in t) for t in towns)
    segments = [(t["code"], t["segment"]) for t in towns if "segment" in t]
    assert len(segments) == len(set(segments))
    attractions = list(wc.read_records(wc.ATTRACTIONS_FILE))
    assert len(attractions) > 10_000
    assert {"Q79961", "Q676203", "Q36332"} <= {a["qid"] for a in attractions}


def test_the_town_index_uses_the_same_rule_as_the_api() -> None:
    rio = TownPoint(uuid.uuid4(), -22.9068, -43.1729, 6_700_000, "rio de janeiro")
    niteroi = TownPoint(uuid.uuid4(), -22.8833, -43.1036, 480_000, "niteroi")
    index = TownIndex([rio, niteroi])
    assert index.nearest(-22.89, -43.11, max_km=50) is niteroi
    assert index.nearest(-22.95, -43.21, max_km=50) is rio
    assert index.nearest(10.0, 10.0, max_km=50) is None
    assert town_popularity(5_000) == pytest.approx(37.0, abs=0.1)
    assert town_popularity(None) == 0.0


def test_an_approximate_box_gives_way_to_a_closer_town() -> None:
    rio, caxias, copacabana, brazil = (uuid.uuid4() for _ in range(4))
    box = Covering(rio, "city", "approximate-bbox", 15.0, wc.town_reach_km(6_700_000))
    near_caxias = NearestTown(caxias, 1.0, wc.town_reach_km(800_000))
    assert _choose(box, near_caxias) == caxias
    licensed = Covering(rio, "city", "osm:2697338", 15.0, 10.0)
    assert _choose(licensed, near_caxias) == rio  # real city limits win
    neighbourhood = Covering(copacabana, "neighborhood", "approximate-bbox", 0.5, 0.0)
    assert _choose(neighbourhood, near_caxias) == copacabana
    country = Covering(brazil, "country", "approximate-bbox", 900.0, 0.0)
    assert _choose(country, near_caxias) == caxias
    assert _choose(country, None) == brazil
    assert _choose(None, None) is None


def test_suggestion_scores_favour_towns_and_well_known_places() -> None:
    assert destination_prominence(150) == pytest.approx(0.35)
    assert destination_prominence(70) > place_prominence(90)  # São Paulo before a namesake place
    assert place_prominence(0) == 0.0
    assert place_prominence(10_000) == pytest.approx(0.2)
    assert like_escape("50%_off\\") == "50\\%\\_off\\\\"
