# ADR-0030: Companions map — approximate start from the IP address, travellers drawn by area

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Product owner (asked for the location from the IP address on a map, a radar-style "search for companions", travellers shown on the map, and a tap to open a profile), mobile and backend
- **Requirements:** LOC-004 (amended), LOC-010 (new), DISC-003, DISC-004, DISC-012 (new), NFR-008
- **Amends:** PRD LOC-004
- **Related:** [ADR-0005](0005-coarse-location-discovery.md) (discovery uses destinations, never coordinates), [ADR-0008](0008-maps-provider-strategy.md) (maps provider, still proposed), [ADR-0021](0021-rate-limit-stores-and-client-ip.md) (client IP)

## Context

The owner wants the Companions tab to work like a detector:

1. The traveller's location appears on a map, worked out from the IP address.
2. "Search for companions" plays a radar sweep, then shows other travellers on the map.
3. Tapping a traveller opens their profile.

Two existing rules apply:

* **LOC-004** said the IP address is never used to infer location for the feed or discovery. IP locations are often wrong (mobile carriers, VPNs), and using them silently would put people somewhere they didn't choose.
* **ADR-0005** keeps discovery at city or neighbourhood level. No API returns coordinates or distances, and even fuzzed positions are ruled out, because repeated sampling leaks them.

[ADR-0008](0008-maps-provider-strategy.md) (MapLibre Native plus a licensed tile provider) is still a proposal. No provider is chosen, the native module isn't installed, and Expo Go can't run it.

## Decision

### 1. An approximate starting point from the IP address

* `GET /v1/users/me/approximate-location` looks up the caller's address (`client_ip()`, as for rate limits) in a **local** copy of DB-IP "IP to City Lite". The database is MMDB format under CC BY 4.0 and is downloaded into the API image at build time. No lookup service sees the address.
* The point is rounded to 0.01° (about 1 km). It is resolved to a covered city the same way as a device fix: an address never places anyone in a neighbourhood. Then the point and the address are discarded. Neither is stored or logged, and `IpLocation` redacts itself in logs and tracebacks.
* The answer describes only the caller:
  * a label such as "Helsinki, Finland";
  * a centre: the covered city's public centroid, or the rounded point;
  * the covered city, or `null` when discovery doesn't cover the area yet.
* **The lookup changes nothing.** The app labels the place as approximate and credits DB-IP. The traveller becomes discoverable only by pressing *Search for companions*, which shares that city as a manual destination choice (`PUT /v1/users/me/discovery-location`, `mode: destination`). "Not here? Choose a city", GPS and city search stay available.
* LOC-004 now reads: the IP address is never used to place anyone silently. It may only suggest a starting point that the traveller sees and can correct.
* The endpoint is behind the `traveler_discovery` flag. A private, unknown or unconfigured lookup answers `422 location_unresolvable`, and the app asks for a city.

### 2. Travellers drawn around the area they share

* The discover API is unchanged and returns area labels only.
* The app draws each traveller around the **public centroid** of the area they share: their neighbourhood, or else the city (`GET /v1/destinations/{id}`).
  * The discover API names a neighbourhood only when both travellers share at neighbourhood level. Otherwise the traveller is drawn around the city centre.
  * Pins sit on a spiral ordered by a hash of the traveller's id: 0.8–2.2 km from a city centre, or 120–420 m from a neighbourhood centre.
  * A pin's spot therefore says nothing beyond the area label.
  * The map says so: "Pins show the area people share, never where they are."
* Tapping a pin opens the profile. Only ids the app put on the map are accepted.
* The same travellers are listed below the map, with Connect. This list is the accessible alternative to the map.

### 3. Rendering

* MapLibre GL JS 5.24.0 runs in `react-native-webview` with OpenFreeMap vector tiles. OpenFreeMap is free, needs no key, allows commercial use and shows OpenStreetMap attribution. The dark style matches the Noir theme; the light theme uses Positron.
* The page is locked down:
  * MapLibre is pinned on jsDelivr and checked with Subresource Integrity.
  * A Content-Security-Policy limits the page to the CDN and the tile host. It cannot navigate, open windows or ask for the device location.
  * Commands arrive as JSON, and names are inserted as text, never as HTML.
  * Messages from the page are validated.
  * Attribution links open in the browser; nothing else leaves the page.
* The radar is a CSS conic sweep anchored on the traveller. Each pin appears as the beam passes its bearing. With "reduce motion" on, pins fade in instead.
* This works in Expo Go and in release builds, with no keys.

### 4. Helsinki in the launch catalog

Finland, Helsinki and its Kallio neighbourhood join the launch catalog. The team's connection resolves to Helsinki, so the staging demo can be tried end to end.

## Consequences

* No new processor sees IP addresses.
  * The database is refreshed whenever the image layer rebuilds, which is every code change. Early in a month it falls back to last month's file.
  * The image is about 130 MB larger.
  * Without the file, the endpoint answers 422 and the app asks for a city.
* OpenFreeMap receives tile requests from the device, so it sees the device's IP address and the area being viewed. This is recorded in docs/15. There is no SLA. ADR-0008's provider decision stays open, and a different style URL can replace OpenFreeMap later.
* If jsDelivr or the tiles are unreachable, the map reports that it can't load, and search and the list still work.
* IP locations are often wrong. The label says "approximate", and choosing another city is one tap away.
* The WebView map is this screen's interim renderer. When ADR-0008 lands, a native map can take the same commands.
* Client IPs come from the platform edge's `X-Forwarded-For` (uvicorn proxy headers). On Railway, spoofed `X-Forwarded-For` and `X-Real-IP` headers had no effect (checked on staging, 2026-11-11). Behind an edge that passed a client-supplied value through, a caller could look up another address. That would only reveal a public database's city for an address they already know, and the per-user `read` limit would still apply.

## Alternatives considered

* **An IP lookup API (ipapi, ip-api, ipinfo):** would send every traveller's address to another company, and the free tiers are for non-commercial use.
* **MaxMind GeoLite2:** similar data, but needs an account and a licence key in the build.
* **react-native-maps (Google Maps):** needs a Maps key with billing on Android, and Google's terms restrict the offline caching ADR-0008 needs.
* **MapLibre Native now:** doesn't run in Expo Go, and the tile provider is undecided.
* **Pins at jittered real positions:** ruled out by ADR-0005.
* **A radar with no map:** doesn't meet the request.
