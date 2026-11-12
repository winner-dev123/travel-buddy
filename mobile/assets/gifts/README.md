# Chat gifts

Illustrations for the chat gifts (DM-016, SCR-081). They were drawn for Travel Buddy, belong to
the project and have no third-party licence. `wrapped.png` is the box a gift arrives in before
the recipient opens it. The other file names are the gift codes from the API
(`contracts/openapi/openapi.yaml`, `GiftCode`).

| File                | Gift          |
| ------------------- | ------------- |
| `coffee.png`        | Coffee        |
| `postcard.png`      | Postcard      |
| `flowers.png`       | Flowers       |
| `ice_cream.png`     | Ice cream     |
| `cake.png`          | Cake          |
| `boarding_pass.png` | Boarding pass |
| `snow_globe.png`    | Snow globe    |
| `coconut.png`       | Coconut       |
| `wrapped.png`       | Wrapped box   |

The sources are the SVG files in `src/` (256 × 256 view box, transparent background). Each PNG
is that SVG rendered at 384 × 384 px, shown at up to 128 points (sharp, `density` 108,
compression level 9). Draw a new gift in `src/` and render it the same way. Adding one also
needs its code in the API catalog (`Gift` in `backend/app/modules/messaging/domain.py`) and in
`src/features/messages/gifts.ts`.

## Opening effects

`effects/` holds the sprites for the effects that play when a gift is opened
(`src/features/messages/GiftEffectOverlay.tsx`): three petal colours (`petal_blush`,
`petal_pink`, `petal_rose`), two water drops (`drop_blue`, `drop_light`) and two hearts
(`heart_red`, `heart_pink`). Confetti and the splash ripples are drawn as plain shapes. The
sources are in `src/effects/` (64 × 64 view box); each PNG is rendered at 96 × 96 px (sharp,
`density` 108, compression level 9). A new effect also needs its code in the API
(`GiftEffect` in `backend/app/modules/messaging/domain.py`) and in `GIFT_EFFECTS`.
