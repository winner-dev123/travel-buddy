# Destination seed data

| File | What it is | Source and license |
|---|---|---|
| `launch_destinations.json` | The editorial launch catalog: countries, cities and neighbourhoods with names, taglines and approximate boundaries | Written for the project |
| `world_cities.jsonl.gz` | Every populated place of 5,000+ people and its country, with names in the app's languages, abbreviations, first-level region, population and time zone (ADR-0035) | [GeoNames](https://www.geonames.org/) dumps `cities5000`, `countryInfo`, `admin1CodesASCII` and `alternateNamesV2`, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit: "GeoNames" |
| `country_names.json` | Country names in the app's languages | [Unicode CLDR](https://cldr.unicode.org/) (through ICU), [Unicode License v3](https://www.unicode.org/license.txt) |
| `world_attractions.jsonl.gz` | Well-known tourist places with coordinates, category and localized names; how well known a place is comes from its Wikipedia/Wikivoyage sitelinks | [Wikidata](https://www.wikidata.org/), [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

The app credits GeoNames and Wikidata in the search sheet. Each imported place records its license and a link to its Wikidata item.

To rebuild and load the files, see `world_catalog.py` and docs/11 §1.6.
