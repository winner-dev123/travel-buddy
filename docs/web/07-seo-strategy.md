# Web 07 — SEO and Discoverability Strategy

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 2 |
| **Owner** | SEO · Web |
| **Builds on** | [Web 01 §5, §12, §14, §15](01-architecture.md) · [Web 02 — Routes and sitemap](02-routes-and-sitemap.md) (normative for robots per route, canonical rules §2.6, locale prefixes §4 and sitemap structure §6) · [PRD](../01-prd.md) (DEST-*, POST-008, AUTH-012, I18N-*) |

This document defines **what** we optimize and **how quality is guarded**. Route-level mechanics (robots directive per route, canonical rules, redirect rules, sitemap files) are specified in 02 and only referenced here.

---

## 1. Goals and non-goals

| Goal | Measure |
|---|---|
| Rank destination pages for "things to do in {city}", "{city} travel guide", "{city} itinerary" in five languages | Impressions and clicks per locale (Search Console), top-10 share for a tracked keyword set |
| Convert organic visitors to registered users | Organic sessions → `/register` → onboarding completion |
| Earn rich results where we are eligible (breadcrumbs, images, profile/post markup) | Search Console enhancement reports with 0 errors |
| Keep private data out of every index | Zero indexed URLs under `(auth)`, `(traveler)`, `admin`, `/api`; zero non-public stories indexed |

Non-goals: SEO for authenticated content; keyword-stuffed doorway pages; programmatic pages without original content; any page presenting live prices, opening hours or travel restrictions that we cannot verify (brief §6, AI-004).

## 2. Indexable surface

| Page type | Route | Content source | Indexing condition | Phase |
|---|---|---|---|---|
| Homepage | `/` | Editorial + featured destinations/stories | Always | 2 |
| Destinations directory | `/destinations` | Catalog | Unfiltered view only (02 §2.1) | 2 |
| Country | `/destinations/[country]` | Catalog editorial | Passes the content threshold (§6.2) | 2 |
| Destination (city) | `/destinations/[country]/[city]` | Catalog editorial + attractions + public stories + FAQs | Passes the content threshold (§6.2) | 2 |
| Attraction | `/destinations/[country]/[city]/attractions/[place]` | Licensed place data + editorial | Published with original description ≥ 120 words | 6 |
| Itinerary landing | `/destinations/[country]/[city]` itinerary section (no separate route in 01 §10) | Editorial sample itineraries, labelled | Part of the city page | 2/6 |
| Public story | `/stories/[storyId]` | User content with `visibility=public`, approved (POST-008) | Public + approved + author not suspended (02 §6.2) | 2 |
| Stories index | `/stories` | Public stories | Page 1 only | 2 |
| Guide | `/guides`, `/guides/[guideId]` | Guide descriptions (never premium bodies or audio URLs) | Published description | 6 |
| Public profile | `/u/[handle]` | Profile | Explicit search-indexing consent only (03 §10 Q1); otherwise `noindex` | 3 |
| Pricing, download, about, legal | — | Static | Always | 2 |

Everything else is `noindex` per 02 §2.2–2.5, and production `robots.txt` disallows `/api/`, the app areas and `/admin` (02 §6.3). `robots.txt` is **not** a privacy control: private routes are also protected by authentication, return `404` to anonymous users, and send `X-Robots-Tag: noindex, nofollow`.

## 3. Rendering for crawlers

* Every indexable page is **server-rendered HTML** (static/ISR per 01 §5 and 02 §2.1). Primary content, headings, internal links and JSON-LD are in the initial HTML. Nothing indexable depends on client-side fetching.
* Public pages never read cookies, so the HTML is identical for crawlers and users (no cloaking) and is CDN-cacheable.
* Personalized islands (Saved, Your plan, Connect) render a neutral server placeholder of fixed size (no CLS) and hydrate after load.
* Maps load lazily and are not required for content comprehension. Every map has a text equivalent (address or area description and a list of places).
* `generateStaticParams` pre-renders all published countries and the top 200 cities per locale. Long-tail pages render on first request and are then cached (ISR). On-demand revalidation by tag (`destination:{id}`, `post:{id}`) runs when content changes (02 §2.1, §9).
* Soft 404s are not allowed. Unknown or hidden resources return HTTP **404** with the localized not-found page. Moved slugs return **308** to the canonical path (02 §2.6).

## 4. Metadata

Built with the Next.js Metadata API (`generateMetadata`) in each route. A single helper, `buildMetadata({ locale, path, title, description, images, robots, alternates })`, in `apps/web/src/lib/seo.ts` produces canonical, `hreflang` alternates, Open Graph and Twitter tags consistently.

### 4.1 Title and description templates

Templates live in `@travelbuddy/i18n` (`seo.*` keys) so every locale writes natural copy instead of machine-assembled fragments.

| Page | Title template (≤ 60 chars target) | Description (≤ 155 chars target) |
|---|---|---|
| Home | `Travel Buddy: explore the world, find your people` | Value proposition |
| Directory | `Destinations: travel guides for {count}+ places` | Directory summary |
| Country | `{Country} travel guide: regions, cities and tips` | First sentence of the country overview, trimmed |
| City | `{City} travel guide: things to do, tips and stories` | Destination tagline + top 3 highlights |
| Attraction | `{Place}, {City}: what to know before you go` | Place short description |
| Story | `{First 50 chars of caption} · {City}` | Caption excerpt (≤ 155), never private fields |
| Guide | `{Guide title}: {City} audio tour` | Guide summary |
| Pricing | `Travel Buddy Premium: plans and benefits` | Benefits summary (no prices in meta; prices vary by market) |

Rules: brand suffix ` | Travel Buddy` is appended by the root `title.template` only when the result stays ≤ 60 characters. Each description is unique per page. Descriptions never contain user emails, handles of non-consenting users, coordinates or dates of upcoming travel.

### 4.2 Canonical and hreflang

Normative rules are in 02 §2.6 and 02 §4. Summary:

| Content | Canonical | hreflang |
|---|---|---|
| Catalog and static pages | Self, per locale (`/destinations/…`, `/es/destinations/…`, `/pt-br/…`, `/fr/…`, `/de/…`) | All five locales + `x-default` → `en` (unprefixed) |
| Public stories | The locale matching the post `language` (else `en`) | None (user content is not translated, I18N-006) |
| Public profiles | `en` unprefixed | None |
| Filtered/paginated views | Path without query, `noindex,follow` | — |

`hreflang` values: `en`, `es`, `pt-BR`, `fr`, `de`, `x-default`. Alternates are generated from the locale registry in `@travelbuddy/i18n`, so adding a locale adds alternates automatically. Every alternate must be reciprocal and return 200. A CI check (§10) validates reciprocity on a sample.

**Untranslated long-form copy:** when a destination overview has no translation for a locale, the page still renders (localized UI, names and FAQs where available), and the English block is marked `lang="en"` with a visible note (01 §12). If **less than 50 %** of the page's main content is in the page locale, that locale variant is `noindex,follow` with a canonical pointing to the `en` variant, and it is omitted from `hreflang`. This avoids publishing thin duplicate pages in five languages.

### 4.3 Open Graph and Twitter cards

| Tag | Source |
|---|---|
| `og:title`, `og:description` | Same as the page title/description (without the brand suffix) |
| `og:type` | `website` (catalog), `article` (stories), `profile` (profiles) |
| `og:url` | Canonical URL |
| `og:locale` / `og:locale:alternate` | `en_US`, `es_ES`, `pt_BR`, `fr_FR`, `de_DE` |
| `og:image` (1200×630) | Licensed destination hero (with credit recorded in the catalog). Otherwise a **generated branded card**: `opengraph-image.tsx` (Next.js `ImageResponse`) using design tokens, destination name and a pattern derived from the destination ID (01 §14). Stories use their first approved image; stories without media use the branded card |
| `twitter:card` | `summary_large_image` |
| `og:image:alt` | Required. Destination/place name or the media `alt_text` |

Images are never taken from private posts, never include EXIF, and never show a user's avatar unless the profile is public. OG images are cached at the CDN with the page's revalidation tag.

## 5. Structured data (JSON-LD)

Rendered server-side by a `<JsonLd data={…} />` component that serializes with `JSON.stringify` and escapes `<`, `>`, `&`, U+2028 and U+2029 (`<` etc.). This is the **only** permitted use of `dangerouslySetInnerHTML` (08 §6). Data is built from typed API responses, never from raw HTML. Markup must describe content visible on the page.

| Page | Types | Key properties | Notes |
|---|---|---|---|
| All pages | `BreadcrumbList` | Home → Destinations → Country → City → Place | Matches the visible breadcrumb |
| Home | `Organization`, `WebSite` | `name`, `url`, `logo`, `sameAs` (official social profiles); `WebSite.potentialAction` `SearchAction` → `/destinations?q={search_term_string}` | Google retired the sitelinks search box in 2024; `SearchAction` is kept because it is valid schema.org and harmless, but it is not expected to produce a rich result |
| Country / City | `TouristDestination` (also `Place`) | `name`, `description`, `url`, `image`, `geo` (`GeoCoordinates` of the public centroid), `containedInPlace` (parent destination), `touristType` (from categories), `includesAttraction` (top attractions as `TouristAttraction` references) | No opening hours, prices or events on destination pages |
| City FAQ block | `FAQPage` | Visible editorial Q&A only | Google limits FAQ rich results to authoritative government/health sites (2023). We keep the markup for semantics and other engines, and expect no rich result |
| Attraction | `TouristAttraction` (+ a more specific type when known, e.g. `Museum`, `Beach`, `Park`) | `name`, `description`, `geo`, `image`, `containedInPlace`, `isAccessibleForFree` only when sourced; `openingHoursSpecification` **only** from licensed data with freshness ≤ provider threshold | Attribution for licensed data is shown on the page |
| Public story | `SocialMediaPosting` | `headline` (caption excerpt), `articleBody` (caption), `datePublished`, `dateModified`, `author` (`Person` with `name` and `url` only if the profile is public; else `name` = display name and no URL), `image`, `contentLocation` (destination `Place`), `interactionStatistic` (`LikeAction`, `CommentAction` counts), `isPartOf` (site) | Never includes precise location, the author's other data, or comments' authors |
| Stories index | `CollectionPage` + `ItemList` | Story URLs | |
| Public profile (opted in) | `ProfilePage` with `mainEntity: Person` | `name`, `alternateName` (handle), `image`, `interactionStatistic` (post count) | Only with indexing consent |
| Guide | `CreativeWork` (`AudioObject` reference for free sample audio only) | `name`, `description`, `inLanguage`, `about` (destination), `isAccessibleForFree` | Premium audio URLs never appear in markup |
| Pricing | `Product` with `Offer` | Only if prices are rendered in HTML for the visitor's market; otherwise omitted | Avoid mismatched price markup across markets |

Validation: schema unit tests per builder (Vitest), the Rich Results Test and the Schema Markup Validator on representative URLs before launch, and Search Console enhancement monitoring afterwards.

## 6. Content quality rules

### 6.1 Editorial principles

1. **Original, verifiable, evergreen.** Destination copy is written or licensed by us, reviewed by an editor, and dated (`content_reviewed_at`). No scraped or spun text.
2. **No unverified live facts.** Prices, opening hours, ticket availability, transit status, safety advisories and entry requirements appear only when sourced from licensed data with a visible freshness date and attribution (DEST-003, AI-004). Otherwise the page links to official sources or omits the fact.
3. **AI content is labelled and never published as editorial.** AI itineraries are user-private unless the user posts an itinerary summary (TRIP-006), which then appears as user content. Editorial "sample itineraries" on destination pages are written or reviewed by editors.
4. **Photos have verified rights.** Licensed catalog images carry `credit` and `licence` (01 §14). Missing images use branded placeholders, never stock photos of another place.
5. **User content respects visibility.** Only `visibility=public` and approved posts are rendered publicly (POST-008). Removal, visibility change, account suspension or deletion de-indexes the URL: the page returns 404, the URL is purged from the CDN and removed from the sitemap within 10 minutes (02 §6.2).
6. **Safety copy.** Destination pages include the safety guidance and local emergency numbers from the catalog where available (doc 08 §7), framed as general guidance, not guarantees.

### 6.2 Indexing threshold for destination pages

A destination page is `index,follow` only when all of these hold. Otherwise it renders for users and is `noindex,follow` until it is enriched (02 §2.1).

| Criterion | City | Country |
|---|---|---|
| Original overview in the page locale (or `en` canonical, §4.2) | ≥ 300 words | ≥ 250 words |
| Attractions with description | ≥ 5 | ≥ 3 featured cities |
| FAQs (editorial) | ≥ 3 | optional |
| `content_reviewed_at` | within 12 months | within 12 months |
| Public stories | not required (stories enrich but never qualify thin pages) | — |

The threshold is evaluated by the backend and exposed as `seo.indexable` on `Destination` (requested from the backend stream, §11) so web and sitemaps agree.

### 6.3 User-generated content protections

* Story pages show author attribution, publication date, destination tags and a **Report** control (brief §6).
* Outbound links in user captions get `rel="ugc nofollow noopener"` and are not auto-linked for accounts younger than 7 days (SAFE-005 spam prevention).
* Spam or low-quality stories (moderation `limited`) are not indexed even if public.

## 7. Internal linking

| From | Links to | Purpose |
|---|---|---|
| Header / footer | Destinations, Stories, Pricing, Download, About, legal; top 10 destinations in the footer per locale | Crawl paths to hubs |
| Directory | Every published country; popular cities per region | Hub → spoke |
| Country | All its cities (paginated list if > 50), parent region | Hierarchy |
| City | Parent country, sibling cities (same country, 6), attractions, latest public stories (≤ 6), related guides, "Plan a trip to {City}" CTA (`/register?intent=trip&destination=`) | Topical cluster |
| Attraction | City, sibling attractions (same category), stories tagged with the place | Cluster depth |
| Story | Destination and place pages, author profile (only if public), 3 related stories from the same destination | Cross-linking UGC into catalog |
| Breadcrumbs | Every level | Hierarchy signals + `BreadcrumbList` |

Rules: descriptive anchor text in the page locale (no "click here"); no links to `noindex` destinations from hubs (they only appear once enriched); all internal links are plain `<a href>` via `next/link` with locale-aware paths, so crawlers can follow them without JavaScript; at most ~150 links per page.

## 8. Internationalization for SEO

* One URL per locale (02 §4): `/…` (en), `/es/…`, `/pt-br/…`, `/fr/…`, `/de/…`. `<html lang>` is set per locale (`pt-BR` for `/pt-br`).
* Locale detection follows 02 §3.1 rule 4 and 02 §4: only **unprefixed** requests without a `NEXT_LOCALE` cookie may be 307-redirected by `Accept-Language`. Prefixed URLs are never redirected. Crawlers typically send no `Accept-Language` and therefore get `en`, while every locale URL is directly reachable and listed in the sitemap with `hreflang`. The redirect is user-agent independent (no crawler special-casing, which would be cloaking), and redirect responses carry `Vary: Accept-Language, Cookie` so CDNs never serve one visitor's redirect to another. IP geolocation is never used (LOC-004).
* Localized destination names come from the catalog (`Accept-Language` → `DestinationSummary.name`, DEST-002) and are used in titles, H1s and breadcrumbs. Slugs remain the catalog slug (one slug per destination across locales) to keep URLs stable. Localized slugs are a later option (§11).
* Currency and units on public pages follow the page locale and are only shown where sourced.

## 9. Performance and Core Web Vitals

Budgets are normative in 01 §15 (public pages: LCP ≤ 2.0 s, INP ≤ 200 ms, CLS ≤ 0.05, first-load JS ≤ 130 KB gzip). SEO-specific practices:

| Practice | Detail |
|---|---|
| LCP element | The hero image or H1. Hero images use `next/image` with `priority`, `fetchPriority="high"`, explicit dimensions, AVIF/WebP and responsive `sizes`. Branded placeholders are CSS gradients (zero bytes over the network) |
| Fonts | `next/font` self-hosted, `display: swap`, subset `latin` + `latin-ext`, size-adjusted fallbacks to avoid CLS |
| JavaScript | Public pages are mostly Server Components. Maps, carousels and the AI demo are lazy islands below the fold |
| Third parties | None before consent. No tag managers on public pages at launch |
| Caching | Static/ISR HTML at the CDN (TTFB ≤ 300 ms cached), `stale-while-revalidate` |
| Monitoring | RUM via `useReportWebVitals` (01 §16), segmented by page type and locale; Lighthouse CI on representative URLs per PR (10 §7) |

## 10. Monitoring and governance

| Tool / check | Cadence | Owner |
|---|---|---|
| Google Search Console + Bing Webmaster Tools: one property per host, sitemaps submitted, coverage, enhancements, CWV, manual actions | Weekly review; alerts on coverage drops > 10 % or new manual actions | SEO |
| Index leak check: `site:` sampling and the Search Console "Indexed" export filtered for `/feed`, `/messages`, `/admin`, `/api`, `/settings`, `/u/` (non-consenting) and non-public story IDs | Weekly; any hit is a P1 incident | SEO + Security |
| CI `seo-check` job (Playwright, part of `ci-web.yml`): for representative pages assert status, `<title>`, meta description, canonical, `hreflang` reciprocity, robots meta + `X-Robots-Tag`, JSON-LD parses and validates against our schema builders, no `noindex` on indexable fixtures, `noindex` on every app/admin route sampled | Every PR | Web |
| Sitemap validation (XML schema, URL count, every URL 200 and canonical) | Nightly on staging | Web |
| Log-based crawl analysis (Googlebot hits by page type, 404/5xx rate for bots) | Monthly | SEO |
| Content freshness report (destinations past 12 months review → drop to `noindex` warning) | Monthly | Editorial |
| Keyword and ranking tracking per locale | Monthly | SEO |

## 11. Open questions / requests

| # | Item | Owner |
|---|---|---|
| 1 | `Destination.seo = { indexable: boolean, reasons: string[] }` computed by the backend from §6.2, so pages and sitemaps agree (request to backend stream) | Backend |
| 2 | Whether to localize slugs (`/es/destinos/brasil/rio-de-janeiro`). Deferred: it multiplies redirects and the catalog would need per-locale slugs with history | Product + SEO |
| 3 | Dedicated itinerary landing pages (`/destinations/[country]/[city]/itineraries`) need editorial capacity. Not in 01 §10; treated as a city-page section until approved | Product |
| 4 | Search-indexing consent field for profiles (03 §10 Q1) blocks profile indexing | Backend |
| 5 | Domain strategy for staging/preview: all non-production hosts must serve `Disallow: /` and global `noindex` (02 §6.1). Preview URLs must not be linked publicly | DevOps |

## 12. Launch checklist (SEO)

- [ ] Production `robots.txt` and sitemap index live; sitemaps submitted in Search Console and Bing.
- [ ] Non-production hosts return `Disallow: /` and `X-Robots-Tag: noindex`.
- [ ] Every indexable template has a unique title, description, canonical and (where applicable) reciprocal `hreflang` + `x-default`.
- [ ] JSON-LD validated with the Rich Results Test for home, country, city, story, attraction (when shipped), profile (opted in).
- [ ] 404 for hidden/missing resources (no soft 404s); 308 for slug moves; no redirect chains > 1 hop.
- [ ] Index leak check: zero private routes or non-public stories in the index.
- [ ] Destination pages below the §6.2 threshold are `noindex` and excluded from sitemaps.
- [ ] CWV budgets met at p75 on lab + early RUM for public templates.
- [ ] OG cards render correctly (Facebook Sharing Debugger, X card validator, LinkedIn Post Inspector, WhatsApp/Telegram previews).
- [ ] Image rights recorded for every catalog image; no unlicensed photography.
- [ ] Analytics respects consent; no third-party scripts before consent.
- [ ] Search Console properties verified for every locale-prefixed path set (domain property).
