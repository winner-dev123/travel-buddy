# ADR-0035: World gazetteer from open data, and search as you type

- **Status:** Accepted
- **Date:** 2026-11-13
- **Deciders:** Product owner (testing on a phone: location features didn't find the real city; asked for city search "like ride apps, without streets, only cities and tourist places"), backend/mobile
- **Requirements:** LOC-003, LOC-005, LOC-008, DEST-001, DEST-003, DEST-006
- **Related:** [ADR-0008](0008-maps-provider-strategy.md) (licensed place data behind a port), [ADR-0030](0030-companions-map-ip-start-and-area-pins.md) (Companions map starts from the IP's city)

## Context

On a phone in Brazil the owner saw location features miss their city. Three causes:

1. **The catalog knew only 44 destinations (19 cities).** Brazil had only Rio de Janeiro. A device elsewhere resolved to "Brazil" or to `location_unresolvable`, and Nearby, Companions and the IP start city all failed.
2. **The phone asked for the least precise fix.** The Android app had coarse location only, which Android fuzzes to about 2 km. It used `Accuracy.Low` and reused any cached position. On top of that it rounded to about 1 km before sending, which is coarser than the 110 m that LOC-003 allows.
3. **Search only knew catalog names.** It was a plain list under a text field.

Ride apps get their search from paid geocoding APIs (Google Places, Mapbox). That would mean API keys, cost per keystroke, a third party seeing every query and position, and results that are not destinations people can post in.

## Decision

1. **Towns and countries from GeoNames, loaded into the catalog.**
   - **Source:** GeoNames `cities5000` (every populated place of 5,000+ people, CC BY 4.0), `countryInfo` and `admin1` for regions, and `alternateNamesV2` for names in the app's five languages and abbreviations. Country names come from Unicode CLDR.
   - **Result:** about 64,500 towns in 243 countries.
   - **Districts dropped:**
     - In countries where GeoNames' second level is the municipality (Brazil, Portugal), a populated place in its seat's municipality is a district of that town (Barra da Tijuca is part of Rio de Janeiro).
     - Numbered districts ("Paris 15 Vaugirard") belong to their city.
   - **Build:** `python -m app.modules.destinations.world_catalog build` writes `seed/world_cities.jsonl.gz` byte for byte reproducibly.
   - **Load:** `… world_catalog load` upserts it.
   - **Paths:**
     - Towns sit directly under their country, so web URLs keep their two segments.
     - Namesakes get their region and then their GeoNames id (`bom-jesus`, `bom-jesus-rio-grande-do-sul`).
     - Paths and slugs never change between runs.
   - **Launch cities** keep their editorial rows. They only gain population, region and GeoNames id.
2. **Out of the directory until listed.**
   - Gazetteer towns are searchable, resolvable, postable and reachable by path. They are absent from `GET /v1/destinations`, children lists and the sitemap: `destinations.in_directory` is false.
   - So 64,000 empty pages don't reach search engines. An editor lists a town when it has content.
3. **Tourist places from Wikidata (CC0).**
   - **What is included:** about 11,800 places with coordinates. They come from 44 classes (monuments, museums, parks, beaches, waterfalls, viewpoints, World Heritage Sites…), each with a minimum number of Wikipedia/Wikivoyage sitelinks as a measure of how well known it is.
   - **What is excluded:**
     - Streets, roads and addresses are never included.
     - Whole historic towns designated World Heritage are excluded: they are destinations.
     - Ruins keep their "demolished" date.
   - **How they are loaded:** places (provider `wikidata`) of the town they belong to, within 50 km. Places already imported from OpenStreetMap with the same Wikidata id are skipped. An editorial takedown survives reloading.
   - **Fetching:** the public SPARQL endpoint refuses some HTTP client libraries. `world_catalog queries` therefore writes the queries, curl fetches them, and `build --wikidata` reads the answers.
4. **A point belongs to the nearest town weighed by size.**
   - `resolve_point` serves `/v1/destinations/resolve`, the Nearby feed, Companions GPS sharing and the IP start city. Order:
     1. A licensed polygon (neighbourhood or city limits) wins.
     2. Otherwise the town with the smallest `distance / (reach + 1 km)` within 80 km. Reach is half the radius of a town of that size at 5,000 people per km², capped at 15 km. A big city keeps its outskirts, and a town across a bay (Niterói) keeps its centre.
     3. An approximate bounding box decides only when no town is closer.
   - This works without PostGIS.
5. **Search as you type: `GET /v1/destinations/suggest`.**
   - **Contents:** one list of towns, neighbourhoods, countries and places to visit (attractions, museums, beaches, viewpoints, parks, trails, markets). A place comes with the destination it is in.
   - **Ranking:**
     - A name that starts with the query beats a word match or typo (0.9 weight).
     - Then a small bonus: towns by population (launch cities highest), places by sitelinks.
     - One or two letters only match the start of names.
   - **Indexes:** every branch is backed by a trigram index. Migration 0049 adds default names and alternative names through the IMMUTABLE `f_search_names(text[])`. `DestinationSummary.region_name` tells namesakes apart.
6. **A "Where to?" sheet in the app.**
   - **Layout:** a full-screen search with the current location first, then the last six choices (kept on the device, forgotten at sign-out), then popular destinations. As you type, results show with an icon and where they are.
   - **Choosing a place:**
     - Explore opens the place.
     - The composer sets its town and tags the place.
     - Other screens take its town.
   - **Screens:** it replaces the separate search lists in Explore, trips, the composer, groups, upcoming trips, onboarding and Companions.
   - **Credit:** the sheet credits GeoNames and Wikidata.
7. **Precise location, the traveller's choice.**
   - **Permission:** the Android app now declares fine location too. Android 12+ lets the traveller pick approximate or precise, as iOS already did. Background location stays blocked.
   - **Fix:**
     - Requested at `Accuracy.Balanced`.
     - A cached position is reused only when within 500 m.
     - A recent rough one is the last resort.
     - Rounded to 3 decimals (about 110 m, LOC-003) on the device.
   - **Explore:** when the OS gives only an approximate position, it explains and links to the settings.

## Consequences

- **Coverage:** every town of 5,000+ people resolves and is searchable, and posts can be filed there. Most have no stories yet; Nearby says so instead of saying the area isn't covered.
- **Size:** the catalog grows by about 64,500 destination rows and 11,800 places (around 80 MB on PostgreSQL with indexes), within the database plan. The seed files add 3.7 MB to the API image.
- **No new runtime dependency or cost:** no third party sees searches or positions.
- **Data freshness:** the data is as fresh as the last build. Rebuilding is a development step (download, build, commit, load).
- **Attribution:** GeoNames attribution (CC BY 4.0) is shown in search and listed in the seed README. Wikidata is CC0, and CLDR is under the Unicode License.
- **Store listings:** they must declare precise location (collected transiently, not stored). See docs/14.
- **Web:** clients gain `region_name` and the suggest endpoint. The web search can switch to `/suggest`, and should `noindex` destinations outside the directory.
