# 13 · DPIA: traveler discovery (draft)

> **Status: draft for review.** Prepared by engineering from the implemented system (BL-2.01..2.03, BL-2.08) to support a GDPR Art. 35 assessment. It is not legal advice. A DPO or privacy counsel must review it, add the consultation record and sign it off before traveler discovery launches in the EU (launch gate T-LOC-10, SAFE-010).

## 1. Processing

| Item | Description |
|---|---|
| Purpose | Let adult travellers who chose to take part see other participating travellers in the same city (or neighbourhood) and ask to connect (PRD DISC-001..010, CONN-*). |
| Data subjects | Registered users aged 18+ (age gate at registration) who turned discovery on. |
| Data | Display name, handle, avatar, bio, travel styles, interests, languages (profile data they entered). A **discovery session**: city, optional neighbourhood (only if the user chose that granularity), optional travel dates, visibility, start and expiry. Upcoming trips the user explicitly marked "share for discovery". Connection requests and connections. |
| Not processed | No coordinates are stored: a GPS point sent to start a session is resolved to a destination and discarded in the same request, and the table has no coordinate column. No distances, no "last seen", no activity timestamps are exposed. |
| Recipients | Other participating users in the same city (traveller cards), staff moderators for reports. Processors: hosting (Vercel) and database (Supabase), under DPAs. |
| Retention | Sessions last at most 72 h and are purged 30 days after they end or expire. Answered connection requests are purged after a year. Account deletion erases everything after the 30-day grace period. |
| Lawful basis | **Consent** (Art. 6(1)(a)): a separate `traveler_discovery` consent, recorded with version and time, withdrawable at any time with immediate effect. |

## 2. Necessity and proportionality

- **Opt-in, off by default.** Discovery is disabled for every new account and cannot be enabled without the recorded consent (enforced by the API, `403 consent_required`).
- **Data minimisation.** Presence is a destination, never a position. Neighbourhood precision is a separate, explicit choice; otherwise only the city is used. Cards show interests and bio only when the user's profile visibility allows it; private and connections-only profiles show identity alone.
- **Reciprocity.** Only participants can browse, and only the city where they are visible (`here_now`) or a destination they share an upcoming trip to (`upcoming`). Invisible users neither appear nor browse, which prevents lurking.
- **Short storage.** Sessions expire automatically (default 24 h, max 72 h); expiry takes effect by query, not by a job.
- **User control.** Go invisible, stop sharing, turn discovery off, withdraw consent, block, report, delete the account — each available in the app.

## 3. Risks to rights and freedoms

| # | Risk | Likelihood before controls | Severity |
|---|---|---|---|
| R1 | Locating a person precisely (stalking) via coordinates or distances | High | High |
| R2 | Triangulating a person by querying from several points | High | High |
| R3 | Tracking movements over time from repeated appearances | Medium | High |
| R4 | Harassment or unwanted contact from strangers | Medium | High |
| R5 | Enumerating who is in a city (scraping, account farms) | Medium | Medium |
| R6 | A blocked person still seeing or reaching the user | Medium | High |
| R7 | Unsafe in-person meetings | Medium | High |
| R8 | Disclosure of sensitive inferences (e.g. from interests or companions) | Low | Medium |
| R9 | Continued processing after the user withdraws | Medium | Medium |

## 4. Measures

| Risk | Measures (implemented unless marked) | Residual |
|---|---|---|
| R1 | No coordinate storage; GPS resolved with PostGIS and discarded (`GeoPointInput` is redacted from logs); responses contain destinations only; integration tests assert no coordinate columns or keys and that submitted values are never echoed (ADR-0005). | Low |
| R2 | Queries take a destination, never a point and radius; no distances anywhere; city is the minimum precision unless the user chose neighbourhood (T-LOC-02). | Low |
| R3 | Sessions ≤ 72 h, purged 30 days after ending; no "last seen"; result order is shuffled within compatibility bands per request so position reveals nothing (T-LOC-04). | Low |
| R4 | Connection requests never connect anyone without an explicit accept; recipient policy (everyone / shared context / nobody); 30-day cooldown after a decline; declined requesters deprioritised in discovery; generic refusal that reveals no reason; reporting with an optional block in the same step; moderation queue with priorities. | Medium |
| R5 | Rate limits: discovery queries (60/min, 500/day), 10 discovery-location changes a day, connection requests (20/day, burst 5/min; 5/day for accounts under 7 days); verified email required to send requests. **Pending:** abuse signals (SAFE-011). | Medium |
| R6 | Blocking removes connections and pending requests in the same transaction and excludes both parties from each other's discovery, profiles and feeds; tested. | Low |
| R7 | Safety guidance before enabling and alongside discovery, never describing meetings as safe (DISC-010); copy pending trust-and-safety review. | Medium |
| R8 | Only data the user entered is shown; no inference of special-category data; profile visibility respected. | Low |
| R9 | Withdrawing consent or turning discovery off removes the user from results immediately (query-time check), even with a session still open; tested. | Low |

## 5. Residual risk and conclusion

With the measures above, residual risk is **low to medium**. Medium risks remain in R4, R5 and R7: harassment and scraping can be reduced but not removed, and in-person safety depends on user behaviour. Before EU launch:

1. Implement abuse signals (SAFE-011) and staff tooling to act on them.
2. Have trust and safety review the safety copy in all five languages.
3. Complete the records of processing and processor DPAs, and confirm the hosting regions for EU users (BL-6.09).
4. DPO review of this assessment, and consultation with the supervisory authority if the reviewed residual risk is judged high (Art. 36).

## 6. Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Engineering (author) | — | 2026-11-09 | Draft prepared |
| DPO / privacy counsel | | | |
| Trust and safety | | | |
| Product owner | | | |
