# ADR-0036: Guides and travel companies marketplace, inquiry first

- **Status:** Accepted
- **Date:** 2026-11-16
- **Deciders:** Product owner (asked for "a platform that connects travel guides and travel service companies with travelers", then chose: part of Travel Buddy, inquiry first with bookings later, staff approval before going live, free at launch with commission, provider plans and featured placement kept for later), backend/mobile
- **Requirements:** PROV-001..PROV-018, DM-001 (exception), SAFE-001/002, ADM-002/009, AUTH-010/011
- **Related:** [ADR-0006](0006-central-entitlement-evaluation.md) (one gate for paid features), [ADR-0031](0031-payments-store-first-stripe-web-ledger.md) (Stripe may be used in the apps for real-world services), [ADR-0032](0032-standalone-staff-console.md) (staff console), [ADR-0035](0035-world-gazetteer-and-place-search.md) (every town is a destination)
- **Design:** [docs/18](../18-provider-marketplace.md)

## Context

Travel Buddy so far serves travelers only: destinations, posts, companions, chat, groups, AI trips and editorial guides. In the PRD a "guide" is a written destination guide, and booking is a v1 non-goal (§1.2).

The owner now wants local tour guides and travel service companies (agencies, tour operators, transfer and activity providers) to register, complete a profile, and be chosen by travelers. Travelers would meet these people in person, often in a country they don't know. The two biggest risks are therefore fake or unlicensed providers, and payment disputes.

What already exists and can be reused: accounts and sessions, the world catalog of towns and places (ADR-0035), media uploads with scanning, real-time chat with an offline outbox (ADR-0033), reports and the moderation queue, the audited staff console, notifications, and a Stripe account (ADR-0031).

## Decision

1. **A provider is its own record, not an account type.**
   - Travelers and providers use the same accounts. A `provider` (kind `guide` or `company`) is a business profile that accounts belong to as `owner`, `manager` or `agent`, the same way group roles are scoped to a group.
   - A person can still travel, post and chat as themselves. They can belong to several companies but own only one individual guide profile.
   - Companies can add staff, who must accept the invitation.
2. **Nobody sees a provider until staff approve it.**
   - Applying means filling in the profile, accepting the versioned Provider Terms, and uploading proof. Proof is an identity document plus the registration the activity needs where the provider works: in Brazil that is CADASTUR for guides (Lei 8.623/1993) and agencies (Lei 11.771/2008), and a CNPJ for companies.
   - Staff holding the new `providers.verify` permission (moderator and above) approve, ask for changes or reject. Every decision needs a justification and is audited, and the applicant is notified.
   - The fields that were checked (kind, legal name, country, registration number) are locked after approval. Changing them goes through staff.
   - Public fields (name, photos, description, areas, languages, offerings) stay editable and fall under reports like any other content.
   - Staff can suspend a provider. Suspension hides it and stops new requests, while existing chats stay readable.
3. **Verification documents are kept to a minimum.**
   - Documents use a new private media purpose. They are never served publicly and never shown to travelers.
   - Staff open them through short-lived signed links, and each opening is audited.
   - The files are deleted 90 days after the decision. The record of the check (document kind, number, expiry, reviewer, time) stays while the provider exists.
   - At first only images are accepted (photos or scans), which reuses the existing scanning pipeline without adding PDF handling.
4. **Phase 1 is inquiries, not payments.**
   - Approved providers publish offerings (tour, activity, transfer, package, class or other) with an indicative "from" price, always labelled as indicative.
   - A traveler sends a request: optional offering, dates or "flexible", party size and a message. The provider accepts or declines it. Payment and final arrangements happen outside the app, which says so plainly.
   - There is no money flow, no commission and no tax or invoicing duty in phase 1.
5. **Requests open a provider chat, the one exception to "connections only".**
   - Messaging gains a fourth conversation kind, `provider`: one thread per provider and traveler pair, reused for later requests. Its members are the traveler and the provider's active members, kept in sync as staff join or leave.
   - The request details (dates, party size, offering, message) live on the inquiry and show as a card in the thread, so creating a request never depends on sending a chat message.
   - Send rights come from a provider policy that messaging calls, like the group policy. Sending is refused when the provider is suspended or deactivated, when either side has blocked the other, or when the marketplace flag is off.
   - The traveler sees the provider's name and logo, and provider members see the traveler.
   - Blocks are kept per provider (`provider_blocks`, from either side), because a person-to-person block can't cover a company with several staff.
6. **Reviews only from real requests.**
   - A traveler can review a provider only after the provider accepted their request and the service date has passed (or the provider marked it completed).
   - It is one review per request, within 60 days, with a rating from 1 to 5 and optional text. The provider may reply once in public.
   - Reviews can be reported and removed by staff. The cached rating on the provider counts visible reviews only.
7. **Finding providers.**
   - `GET /v1/providers?destination_id=` lists approved providers whose home town or service areas are that destination or any place inside it. So a provider serving Rio de Janeiro shows on Copacabana, and a country page shows providers in its towns.
   - Results can be filtered by kind, language and specialty. Approved providers and published offerings can be read without an account (like free guides), so the web can index them later.
   - The ranking is deterministic: rating with a small-sample penalty, response rate, then most recently active. Any sponsored slot added later must carry a label and stay separate from that ranking.
8. **Behind one flag, `provider_marketplace`, default off.**
   - The flag covers browsing, applying, requests and provider chat. Bookings will get their own flag (`provider_bookings`).
9. **Phase 2: paid bookings and revenue (not built now).**
   - **Bookings:** Stripe Connect Express accounts for providers, with destination charges and an application fee as the commission. ADR-0031 already allows Stripe inside the apps for real-world services. Phase 2 also adds availability, cancellation policies, refunds and disputes, payouts, and marketplace invoicing (NFS-e in Brazil).
   - **Provider plans:** monthly plans for extra tools, sold on the web through the existing Stripe setup and granted through `billing.service.has()` (ADR-0006).
   - **Featured placement:** paid spots labelled "Sponsored".
   - Each part needs its own ADR and a legal check of marketplace liability and consumer law in the launch countries before it ships.

## Consequences

- The PRD gains area PROV (§4.22). The §1.2 booking non-goal is narrowed: no booking or reselling of flights, hotels or tickets in v1, and paid bookings with guides and companies come only in phase 2.
- Migration 0050 adds 8 tables (`providers`, `provider_members`, `provider_service_areas`, `provider_documents`, `provider_offerings`, `provider_inquiries`, `provider_reviews`, `provider_blocks`). It also adds conversation kind `provider`, report targets `provider`, `provider_offering` and `provider_review`, media purposes `provider` (public photos) and `provider_document` (private), and four notification types.
- The deletion saga hands a company to its next manager, or deactivates it, before an owner is erased. An individual guide profile is deactivated and its public text cleared. Reviews by erased travelers stay, attributed to "Former traveler". The data export includes memberships, applications, offerings, requests and reviews.
- Records of processing (docs/15) gain one activity: provider verification (identity documents, legal obligation and legitimate interest, 90-day file retention). The threat model gains provider impersonation, fake reviews and off-platform payment scams. Travelers see safety tips before their first request.
- Provider chat is the first conversation between people who aren't connected. Rate limits apply: 10 new requests a day per traveler, one open request per traveler and provider, plus the existing message limits.
- The new-connection keyword filter (SAFE-006) doesn't apply to provider chats. In phase 1 the two sides arrange payment in that chat, so payment terms would be blocked. Reports, blocks and suspension cover abuse instead.
- Phase 1 needs no legal entity changes and no payment setup, so it can launch as soon as staff are available to review applications.

## Alternatives considered

- **Separate product:** a cleaner brand split, but it duplicates identity, chat, moderation and the console. Rejected by the owner.
- **Provider as an account type (one account = one business):** simpler, but a guide couldn't also travel as themselves, and companies with several staff would share one login.
- **Directory with public contact details (WhatsApp, phone):** the fastest option, but conversations are unprotected, there is nothing to tie reviews to, and nothing to build bookings on later.
- **Paid bookings from day one:** commission revenue sooner, but refunds, disputes, payouts and marketplace invoicing would all land in the first release. Deferred to phase 2.
- **Live at once with a "Verified" badge later:** faster growth, but travelers meet these people in person, so approval comes first.
- **Reusing direct messages with an automatic connection:** fewer changes in messaging, but it would give provider staff a person-to-person link to the traveler, and team access would be lost.
