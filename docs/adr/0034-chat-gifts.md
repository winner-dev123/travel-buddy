# ADR-0034: Chat gifts as a fixed catalog of free presents

- **Status:** Accepted
- **Date:** 2026-11-12
- **Deciders:** Product owner (asked for gift images to send and receive presents next to the emoji), backend/mobile
- **Requirements:** DM-016, DM-005, DM-014, SAFE-006

## Context

Travellers asked for a way to send a small present in a chat: a picture they choose, which the other person "receives" and opens, next to the emoji they already use. Three things shape the design:

- **Money.** Virtual gifts are often sold. Selling one would be a digital purchase that needs App Store / Google Play billing in the apps (ADR-0031). A gift with a value that can be cashed or converted also creates fraud and pressure risks between people who met recently.
- **Poor networks.** Chat has to keep working on very poor networks (DM-014, ADR-0033). A gift that needs a download before it shows would break that.
- **One recipient.** "Opened" only makes sense when a gift has exactly one recipient.

## Decision

1. **A fixed catalog of free gifts.** Eight illustrated presents with travel themes: coffee, postcard, flowers, ice cream, cake, boarding pass, snow globe and coconut. They are free and unlimited. They can't be bought, sold, cashed or converted, and they unlock nothing.
2. **The pictures ship with the apps.** They are bundled assets: `mobile/assets/gifts`, PNG at 384 px rendered from SVG sources drawn for the project. A gift therefore shows offline at once. An app that doesn't know a newer gift shows the wrapped box and "Gift".
3. **A gift is a message.** It is a message of kind `gift` naming a code (`gift_code`). It has no body or attachments of its own, so the keyword filter has nothing to check (SAFE-006), and it can't carry a hidden note.
   - It uses the normal send path: idempotent `client_message_id`, the offline outbox, the rate limit, messaging restrictions, blocks and the connection rule.
   - It can be reported and unsent like any message. It can't be edited.
   - The API checks the catalog; the database only checks that a gift names a code. Adding a gift is an app release plus one enum value, with no migration.
4. **Direct chats only.** Only the other member opens a gift: `POST /v1/conversations/{id}/messages/{messageId}/gift/open`. Opening is idempotent and records `gift_opened_at`.
   - The first open sends `message.updated` with change `gift_opened`, so the sender sees "Opened" live.
   - Group chats refuse gifts (`422`, field `/kind`). The app offers only emoji there.
5. **"Sent you a gift".** The new-message notification for a gift says so, in the reader's language. Other messages keep the generic text, and message contents stay out of notifications.
6. **An emoji panel next to it.** A smiley button inside the message field opens a panel with two tabs, Emoji and Gifts.
   - Emoji are added to the text.
   - A gift is first chosen, then sent with its own button, so a stray tap never sends one.
   - The button sits on the send button's side of the field, so it follows the left-handed layout (DM-015).

## Consequences

- No billing, ledger or store review questions: gifts have no price. Selling gifts later would be a new decision, going through store billing (ADR-0031).
- New gifts need an app release before people can send them. Older apps still show them, as a wrapped box.
- Clients that render messages (the web app) need the `gift` kind and the `gift` field on `Message`. The contract and the generated web types are updated. Until the web shows the pictures, it can show the gift's name.
- Opening works from the wrapped bubble with a short reveal animation. It shows at once and is confirmed by the server. It retries on a dropped connection; if the server refuses, the gift goes back to wrapped with a message.

## Amendment (2026-11-12): opening effects

The sender also picks what plays on screen when the gift is opened: **flower petals** (the default), a **water splash**, **confetti** or **hearts**.

- The choice is stored with the gift (`messages.gift_effect`, migration 0048) and returned as `gift.effect`. `SendMessageRequest.gift_effect` and the `message.send` frame take it; when it is omitted, the gift opens with petals. Gifts sent before effects existed were set to petals.
- Like the catalog, the list of effects is checked by the API, not the database, so a new effect is an app release plus one enum value. An app that doesn't know an effect plays petals.
- The apps draw the effects: a full-screen layer over the chat that never takes touches, is hidden from screen readers, and runs on the native animation driver for about three to four seconds. Petals, drops and hearts are small bundled sprites (`mobile/assets/gifts/effects`); confetti and ripples are plain shapes.
- It plays for the recipient when they tap to open, and for the sender when the opening arrives while that chat is open. Tapping an opened gift plays it again. Picking an effect in the panel plays a preview.
- Nothing plays when the system asks for reduced motion.
- The effect isn't shown on a wrapped gift, so it stays a surprise. Once opened, the gift's caption shows the effect's emoji.

## Alternatives considered

- **Sticker packs downloaded from the server.** More flexible, but a gift wouldn't show offline until downloaded, and it needs a media pipeline and moderation for packs. Rejected for now.
- **Paid gifts or gift coins.** Rejected: store billing, refunds and the risk of moving value between strangers, for a feature whose point is a friendly gesture.
- **Gifts in group chats, for everyone.** "Opened" would need a row per member, and a present to a whole group reads oddly. Left out; it can be added with a per-member table if wanted.
- **A gift as an image message.** Reusing photo messages would upload a file per gift, lose the "wrapped, then opened" state and look like any photo. Rejected.
