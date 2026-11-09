# Web 04 — Design System and Component Inventory

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 1 |
| **Covers** | Required output #5 (design system) and #6 (reusable component inventory) |
| **Anchor** | [Web 01](01-architecture.md) §13 (token summary), §14 (imagery), §15 (performance budgets), §12 (RTL) |
| **Source of truth in code** | `packages/ui/src/tokens.css` (CSS custom properties + Tailwind CSS 4 `@theme`), `packages/ui/src/tokens.ts` (the same values as plain TS for React Native) |
| **Requirements** | NFR-008 (WCAG 2.2 AA), I18N-004 (RTL-ready), OFF-003 (online-only labelling), PRD [§4](../01-prd.md#4-functional-requirements) |

If this document and `tokens.css` disagree, the code is a bug. Fix one or the other in the same PR.

---

## 1. Principles

1. **Editorial travel, not SaaS.** Public pages read like a travel magazine: a large serif display, generous whitespace, photography-first cards, warm paper backgrounds. The traveler app is calmer and denser but keeps the same voice. Admin is purposefully plain.
2. **Accessible by construction.** Every colour pairing in §2 has a measured contrast ratio. Every interactive primitive comes from Radix (focus management, keyboard support, ARIA), so a11y is not re-implemented per feature. Target: WCAG 2.2 AA (NFR-008).
3. **Honest UI.** The design never implies something the platform cannot guarantee: no fake live data, no "safe" claims about strangers (DISC-010), no simulated payments, and mock data is always labelled (01 §7.1).
4. **One token set, three experiences.** Public, traveler and admin share tokens. They differ in density and layout, not colour or type.
5. **Logical properties only.** `ms-*`, `me-*`, `ps-*`, `pe-*`, `start-*`, `end-*`, `text-start`. Never `left`/`right` in component code (I18N-004).

## 2. Colour

### 2.1 Brand and surface tokens

Values are exactly 01 §13. Ratios are WCAG 2.x relative-luminance contrast, measured against the stated background.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--color-primary` | `#087F8C` Ocean Blue | `#2FB3BF` | Primary buttons, links, active nav, focus ring |
| `--color-primary-foreground` | `#FFFFFF` | `#0E1A1D` | Text/icons on primary |
| `--color-secondary` | `#15B8A6` Tropical Teal | `#2DD4BF` | Decorative fills, chips, illustrations, progress |
| `--color-secondary-foreground` | `#17252A` | `#0E1A1D` | Text on secondary (**dark only**) |
| `--color-secondary-strong` | `#0F766E` | `#2DD4BF` | Teal used **as text or icon** on light surfaces |
| `--color-accent` | `#FF735C` Sunset Coral | `#FF8A75` | Conversion CTAs ("Join free", "Plan my trip"), highlights |
| `--color-accent-foreground` | `#17252A` | `#0E1A1D` | Text on accent (**dark only**) |
| `--color-accent-strong` | `#C2412D` | `#FF8A75` | Coral used **as text or icon** on light surfaces |
| `--color-background` | `#FAFAF7` | `#0E1A1D` | Page background |
| `--color-surface` | `#FFFFFF` | `#142429` | Cards, panels, inputs |
| `--color-surface-raised` | `#FFFFFF` | `#1A2E34` | Popovers, menus (dark: lighter instead of a shadow) |
| `--color-surface-sunken` | `#F2F3EE` | `#0A1417` | Wells, code, skeleton base |
| `--color-foreground` | `#17252A` | `#ECF2F1` | Body text |
| `--color-muted-foreground` | `#5F6D71` | `#9DB0B3` | Secondary text, captions, meta |
| `--color-slate` | `#69777B` | `#9DB0B3` | Brief's original secondary text. **Icons and large text (≥ 24 px, or ≥ 18.66 px bold) only** |

### 2.2 Measured contrast

| Pair | Ratio | AA normal (4.5) | AA large / UI (3.0) |
|---|---|---|---|
| `#17252A` on `#FAFAF7` | 15.1:1 | ✓ | ✓ |
| `#17252A` on `#FFFFFF` | 15.7:1 | ✓ | ✓ |
| `#5F6D71` on `#FAFAF7` | 5.1:1 | ✓ | ✓ |
| `#5F6D71` on `#FFFFFF` | 5.4:1 | ✓ | ✓ |
| **`#69777B` on `#FAFAF7`** (brief value) | **4.44:1** | **✗** | ✓ |
| `#087F8C` on `#FFFFFF` | 4.75:1 | ✓ | ✓ |
| `#087F8C` on `#FAFAF7` | 4.54:1 | ✓ (narrow) | ✓ |
| `#FFFFFF` on `#087F8C` (primary button) | 4.75:1 | ✓ | ✓ |
| **`#FFFFFF` on `#15B8A6`** | **2.49:1** | **✗** | **✗** |
| `#17252A` on `#15B8A6` | 6.3:1 | ✓ | ✓ |
| `#0F766E` on `#FAFAF7` | 5.2:1 | ✓ | ✓ |
| **`#FFFFFF` on `#FF735C`** | **2.67:1** | **✗** | **✗** |
| `#17252A` on `#FF735C` (accent button) | 5.9:1 | ✓ | ✓ |
| `#C2412D` on `#FAFAF7` | 4.9:1 | ✓ | ✓ |
| `#ECF2F1` on `#0E1A1D` | 15.7:1 | ✓ | ✓ |
| `#ECF2F1` on `#142429` | 14.1:1 | ✓ | ✓ |
| `#9DB0B3` on `#0E1A1D` | 7.9:1 | ✓ | ✓ |
| `#9DB0B3` on `#142429` | 7.1:1 | ✓ | ✓ |
| `#2FB3BF` on `#0E1A1D` / `#0E1A1D` on `#2FB3BF` | 7.0:1 | ✓ | ✓ |
| `#2FB3BF` on `#142429` | 6.3:1 | ✓ | ✓ |
| `#0E1A1D` on `#2DD4BF` | 9.5:1 | ✓ | ✓ |
| `#0E1A1D` on `#FF8A75` | 7.7:1 | ✓ | ✓ |

**Rules that follow from the table:**

* **AA adjustment.** The brief's secondary text `#69777B` measures 4.44:1 on the warm background, just under AA for body text. Body-size secondary text uses `--color-muted-foreground` `#5F6D71` (5.1:1), which is visually almost identical. `#69777B` survives as `--color-slate` for icons and large text, where 3:1 applies.
* **Teal and coral never carry white text.** Buttons, badges and chips filled with `--color-secondary` or `--color-accent` use the dark foreground token. The primary (Ocean Blue) is the only brand fill that carries white text.
* **Teal and coral as text** on light surfaces use the `-strong` variants. In dark mode the base values already pass.
* **Never rely on colour alone.** Status always pairs colour with an icon and text (for example ✓ Connected, not a green dot).

### 2.3 Semantic tokens

| Token | Light (text / fill) | Dark (text / fill) | Contrast (text on background) | Use |
|---|---|---|---|---|
| `--color-success` | `#15803D` | `#4ADE80` | 4.8:1 light · ≥ 10:1 dark | Confirmations, "Connected", correct answer |
| `--color-warning` | `#A16207` text · `#F59E0B` fill with `#17252A` text | `#FBBF24` | 4.9:1 light | Grace periods, expiring discovery, restrictions |
| `--color-danger` | `#C62828` (white text on fill: 5.6:1) | `#F87171` (dark text on fill) | 5.6:1 light · 6.6:1 dark | Destructive actions, errors, validation |
| `--color-info` | `#2563EB` | `#60A5FA` | 5.2:1 light · 7.0:1 dark | Neutral notices, "Mock data" banner border |
| `--color-*-subtle` | 8–12 % tint of the hue on surface | 16 % tint on surface | n/a (backgrounds only; text on them uses the base hue) | Alert and toast backgrounds |
| `--color-border` | `#E3E6E1` | `#23383E` | decorative (< 3:1 allowed) | Card outlines, dividers |
| `--color-input` | `#7E8B8E` (3.5:1 on white, 3.4:1 on background) | `#5C7378` (3.2:1 on surface) | ≥ 3:1 (WCAG 1.4.11) | Borders of inputs, checkboxes, switches (identifying boundaries) |
| `--color-ring` | `#087F8C` | `#2FB3BF` | ≥ 4.5:1 against background | Focus ring |
| `--color-overlay` | `rgb(14 26 29 / 0.60)` | `rgb(0 0 0 / 0.70)` | — | Dialog and sheet scrims |
| `--color-scrim-hero` | `linear-gradient(to top, rgb(14 26 29 / .75), transparent 60%)` | same | Guarantees ≥ 4.5:1 for white text over photos | Text over imagery |

### 2.4 Data visualisation (admin)

Admin charts use an AA-checked categorical set derived from the brand: `#087F8C`, `#C2412D`, `#6D28D9`, `#A16207`, `#15803D`, `#475569`. Every chart offers a table view, and series are distinguished by marker shape as well as colour.

## 3. Typography

| Family | Token | Use | Loading |
|---|---|---|---|
| **Fraunces** (variable serif, `opsz` axis) | `--font-display` | Marketing headlines, destination names, story titles, empty-state headlines | `next/font/google`, self-hosted at build, `display: swap`, subsets `latin`, `latin-ext` |
| **Plus Jakarta Sans** (variable sans) | `--font-sans` | All UI and body text, app headings, admin | same |
| System monospace | `--font-mono` | IDs, request references, admin audit data | system stack |

`latin-ext` covers es, pt-BR, fr and de. Adding a script (for example Arabic for an RTL locale) means adding a font subset per locale, not changing components.

### 3.1 Scale

Base 16 px (`1rem`). Display sizes are fluid between 360 px and 1280 px viewports.

| Token | Size | Line height | Weight | Tracking | Family | Use |
|---|---|---|---|---|---|---|
| `display-2xl` | `clamp(2.75rem, 1.6rem + 4.2vw, 4.5rem)` (44→72 px) | 1.05 | 600 | -0.02em | Fraunces | Homepage hero |
| `display-xl` | `clamp(2.25rem, 1.5rem + 2.8vw, 3.5rem)` (36→56) | 1.10 | 600 | -0.015em | Fraunces | Destination hero names |
| `display-lg` | `clamp(1.875rem, 1.4rem + 1.6vw, 2.5rem)` (30→40) | 1.15 | 600 | -0.01em | Fraunces | Marketing section titles |
| `heading-xl` | 1.75rem (28) | 1.25 | 700 | -0.01em | Jakarta | App page titles (h1) |
| `heading-lg` | 1.375rem (22) | 1.30 | 700 | 0 | Jakarta | Section headings (h2) |
| `heading-md` | 1.125rem (18) | 1.40 | 600 | 0 | Jakarta | Card titles (h3) |
| `heading-sm` | 1rem (16) | 1.40 | 600 | 0 | Jakarta | Sub-sections, table headers |
| `body-lg` | 1.125rem (18) | 1.60 | 400 | 0 | Jakarta | Marketing lead paragraphs, story body |
| `body` | 1rem (16) | 1.60 | 400 | 0 | Jakarta | Default |
| `body-sm` | 0.875rem (14) | 1.50 | 400 | 0 | Jakarta | Meta, dense lists, admin tables |
| `caption` | 0.75rem (12) | 1.40 | 500 | 0.01em | Jakarta | Timestamps, credits, helper text |
| `overline` | 0.75rem (12) | 1.20 | 700 | 0.08em, uppercase | Jakarta | Eyebrows ("POPULAR DESTINATIONS") |

**Rules.** Form inputs are never smaller than 16 px on mobile (this prevents iOS zoom). Long-form text is capped at `68ch`. Metrics and counters use `font-variant-numeric: tabular-nums`. Text resizes to 200 % without loss of content (WCAG 1.4.4); no fixed heights on text containers. German compounds and French spacing need room: buttons and tabs never truncate labels with a fixed width. They wrap or use `hyphens: auto` with `lang` set.

## 4. Spacing, sizing and radius

### 4.1 Spacing scale (4 px base, Tailwind defaults)

| Token | px | Token | px | Token | px |
|---|---|---|---|---|---|
| `0.5` | 2 | `4` | 16 | `12` | 48 |
| `1` | 4 | `5` | 20 | `16` | 64 |
| `1.5` | 6 | `6` | 24 | `20` | 80 |
| `2` | 8 | `8` | 32 | `24` | 96 |
| `3` | 12 | `10` | 40 | `32` | 128 |

| Layout constant | Value |
|---|---|
| Page gutter | 16 px mobile · 24 px tablet · 32 px desktop |
| Marketing section rhythm | `py-16` mobile · `py-24` desktop |
| Container max width | 1280 px (marketing and app content). Prose 68ch. Admin fluid to 1536 px |
| Minimum target size | 44 × 44 px for touch targets (WCAG 2.5.8 needs 24 × 24; we exceed it). Dense admin tables use 32 px rows with 44 px hit areas on actions |
| Sidebar widths | Traveler 264 px expanded / 72 px rail · Admin 248 px · Messages list 320 px · Assistant sheet 420 px |

### 4.2 Radius

| Token | Value | Use |
|---|---|---|
| `--radius-xs` | 4 px | Badges, small tags |
| `--radius-sm` | 6 px | Checkboxes, tooltips |
| `--radius-md` | 10 px | Buttons, inputs, menu items |
| `--radius-lg` | 14 px | Cards, popovers |
| `--radius-xl` | 20 px | Media cards, dialogs, sheets (top corners on mobile) |
| `--radius-2xl` | 28 px | Hero search, feature panels |
| `--radius-full` | 9999 px | Avatars, chips, pills, FAB |

## 5. Elevation, motion and layers

### 5.1 Shadows and elevation

| Level | Light shadow | Dark treatment | Use |
|---|---|---|---|
| 0 | none | `--color-surface` | Flat content |
| 1 | `0 1px 2px rgb(23 37 42 / .06), 0 1px 3px rgb(23 37 42 / .08)` | surface + 1 px `--color-border` | Cards, post cards |
| 2 | `0 4px 12px -2px rgb(23 37 42 / .10)` | `--color-surface-raised` + border | Hover cards, dropdowns, popovers, sticky header after scroll |
| 3 | `0 12px 32px -8px rgb(23 37 42 / .18)` | `#20363D` + border | Dialogs, sheets |
| 4 | `0 24px 64px -12px rgb(23 37 42 / .25)` | `#20363D` + border | Hero search panel, toasts |

Dark mode communicates elevation with lighter surfaces, because shadows are invisible on dark backgrounds.

### 5.2 Motion

| Token | Value | Use |
|---|---|---|
| `--duration-instant` | 75 ms | Press feedback, toggle thumb |
| `--duration-fast` | 150 ms | Hover, colour, focus, small fades |
| `--duration-base` | 220 ms | Menus, popovers, tabs, accordions |
| `--duration-slow` | 320 ms | Dialogs, sheets, drawers |
| `--duration-slower` | 480 ms | Hero reveals, page-level transitions |
| `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Most transitions |
| `--ease-enter` | `cubic-bezier(0.05, 0.7, 0.1, 1)` | Elements entering (sheets, toasts) |
| `--ease-exit` | `cubic-bezier(0.3, 0, 0.8, 0.15)` | Elements leaving |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Reaction "pop", bookmark (≤ 220 ms) |

**`prefers-reduced-motion: reduce`:** all transforms, parallax, scale "pops", carousel auto-advance and map `flyTo` animations are disabled (maps use `jumpTo`). Skeleton shimmer becomes a static tint. Video never autoplays. Opacity fades stay but cap at 150 ms. Nothing essential depends on animation. The motion tokens are redefined inside the media query, so components need no per-component handling.

### 5.3 Z-index layers

| Layer | z-index | Contents |
|---|---|---|
| base | 0 | Content |
| raised | 10 | Sticky in-content elements (table headers, tab bars) |
| header | 30 | SiteHeader, traveler top bar, MobileBottomNav |
| fab | 35 | Create-post FAB |
| sidebar-overlay | 40 | Expanded rail overlay on tablet |
| sheet | 50 | Sheets and drawers (+ their scrim) |
| dialog | 60 | Dialogs (+ scrim) |
| popover | 70 | Dropdowns, popovers, comboboxes (they must sit above a dialog that contains them) |
| toast | 80 | Toast viewport |
| tooltip | 90 | Tooltips |
| skip-link | 100 | "Skip to content" when focused |

EnvironmentBanner is in normal document flow at the top of `<body>`. It is never fixed over content.

### 5.4 Focus states

* **Spec:** `outline: 2px solid var(--color-ring); outline-offset: 2px;` on `:focus-visible` only (no ring on mouse click). The offset gap shows the page background, so the ring sits against the background (≥ 4.5:1 in both themes) even on coral or teal components.
* Inside dark imagery (hero cards), components use `--ring-on-media`: a white 2 px ring plus a 4 px `rgb(14 26 29 / .6)` halo, keeping ≥ 3:1 against any photo.
* Focus is never removed (`outline: none` is banned by lint unless a replacement ring is applied in the same rule).
* Focus is never obscured by sticky header or bottom nav (WCAG 2.4.11): `scroll-padding-top` and `scroll-padding-bottom` equal to their heights.
* Dialogs and sheets trap focus, restore focus to the trigger on close, and close on `Esc` (Radix default).

## 6. Breakpoints and layout

| Token | Min width | Device class | Traveler shell | Public site | Admin |
|---|---|---|---|---|---|
| (base) | 0 | Mobile | Top app bar + **MobileBottomNav** (5 items) | Compact header + menu Sheet | Drawer nav |
| `sm` | 640 px | Large phone | same | 2-column card grids | same |
| `md` | 768 px | Tablet | **72 px icon rail** sidebar, no bottom nav | Header links collapse to a menu; 2–3 column grids | Drawer nav |
| `lg` | 1024 px | Small desktop | Icon rail. Messages and explore become two-pane | Full header nav; 3-column grids; directory sidebar filters | Sidebar 248 px |
| `xl` | 1280 px | Desktop | **Expanded 264 px sidebar**; assistant as a non-modal side panel | 4-column destination grid | Optimized target |
| `2xl` | 1536 px | Wide | Content max 1280 px, centred; optional right rail (trending destinations) on feed | same | Fluid tables |

### 6.1 Responsive behaviour per device class (brief §5)

| Pattern | Desktop (≥ 1024) | Tablet (768–1023) | Mobile web (< 768) |
|---|---|---|---|
| Navigation | Sidebar (expanded ≥ xl, rail lg) | Icon rail with tooltips | Bottom navigation + "More" menu |
| Layout | Multi-column: feed + right rail; explore split-screen (list start, map end) | Reduced columns; explore list/map split at lg only, toggle below | Single column; explore uses a **map/list toggle** |
| Maps | Large interactive maps, persistent | Half-height map | Full-screen map mode, toggle back to list |
| Messaging | Persistent conversation panel beside the thread | Two-pane at lg, list-or-thread below | List-or-thread; composer pinned above the keyboard (`visualViewport`) |
| Modals | Centred Dialog (max 560 px), composer max 720 px | Dialog | **Full-screen Sheet** (composer, filters, onboarding steps, report) |
| Interaction | Hover affordances allowed **in addition to**, never instead of, visible controls; drag-and-drop for itinerary with keyboard alternative | Touch-first, 44 px targets, no hover-only UI | Touch-first, swipe allowed only as a shortcut for a visible action |
| Upload | Drag-and-drop zone + file picker | File picker + camera | File picker + camera capture (`accept`, `capture`) |

## 7. Theming

* **Mechanism:** `data-theme="light" | "dark"` on `<html>`. With no attribute, the theme follows `prefers-color-scheme` through `@media` rules in `tokens.css`. All colours are CSS variables, so a theme switch is a repaint, never a re-render.
* **Preference storage:** `localStorage["tb-theme"]` = `light | dark | system`. It is stored per device; theme is not a server preference, because public pages are static and cannot read cookies (01 §5).
* **No flash:** a tiny inline script in `<head>` (before paint) reads the preference and sets `data-theme`. It is the only inline script on public pages and is allowed by a CSP **hash** (static pages cannot carry per-request nonces). See [08 — Security](08-security-privacy.md).
* `color-scheme: light dark` is set so native controls and scrollbars match.
* The `ThemeToggle` offers three states (Light, Dark, System) as a radio menu.
* Images: brand placeholders have dark-mode palettes. Photos get no filter. Logos use `currentColor` SVGs.

## 8. Voice and tone

| Principle | Do | Don't |
|---|---|---|
| Warm and curious | "Where to next?" · "Rio is waiting." | Hype: "The #1 travel app!!!" |
| Clear and concise | "Post published." | "Your post has been successfully published to the platform." |
| Honest about limits | "AI suggestions — check opening hours before you go." · "Estimated" labels | Presenting AI estimates as facts; "verified" without a source |
| Safety without fear | "Meet in busy public places and tell a friend where you're going." (doc 08 §7) | "Safe", "verified travelers" or any guarantee about strangers (DISC-010) |
| Respectful and inclusive | Gender-neutral second person; no assumptions from nationality | Idioms that do not translate; jokes in error messages |
| Errors that help | What happened + what to do + "Reference: 0193…" | Blame ("You did something wrong"), raw codes, stack traces |
| Empty states that invite | "No posts from Lisbon yet. Be the first to share a tip." + action | "No data." |

All strings live in `@travelbuddy/i18n` catalogs with ICU plurals. Copy is written for translation: no string concatenation, full sentences with placeholders.

## 9. Iconography

* **Library:** Lucide (tree-shaken per-icon imports). Default stroke 1.75 at 20 px. Sizes: 16 (inline meta), 20 (UI default), 24 (nav, primary actions), 32+ (empty states only).
* Nav items always pair icon and label. The icon rail exposes the label as tooltip and accessible name.
* Icon-only buttons (`IconButton`) require `aria-label` (enforced by the component's TS type) and show a tooltip on hover/focus.
* Decorative icons get `aria-hidden="true"`.
* **RTL:** directional icons (arrows, chevrons, "back", "send") mirror via `rtl:-scale-x-100`. Non-directional icons (search, heart, clock) and media transport controls (play, pause) do not mirror.
* Brand marks (App Store, Google Play badges) use the official artwork per their guidelines, never Lucide approximations.

## 10. Imagery and placeholders

Rules from 01 §14 apply. They are made concrete here:

| Rule | Detail |
|---|---|
| Sources | Platform media or licensed catalog photography with `credit` and `licence` on the record. No hotlinking, no stock imagery of a different place. |
| Credit | When a photo carries `credit`, it is rendered as a `caption` overlay (heroes) or in the image `figcaption`. |
| **DestinationPlaceholder** | Deterministic from `hash(destination_id)`: one of **8 gradient palettes** built from brand hues (ocean→teal, teal→sand `#F4E9D8`, coral→sunset `#FFB38A`, ocean→night, …), one of **4 SVG patterns** (topographic contours, waves, compass grid, dotted route line) at 12 % opacity, and the destination name in Fraunces. The same destination always renders the same artwork on web and mobile, using the same algorithm from `@travelbuddy/ui` tokens. The pattern is `aria-hidden`; the visible name is the accessible text. |
| Avatar fallback | Initials (max 2 graphemes, Unicode-aware) on one of 6 AA-safe background colours chosen by `hash(user_id)`. |
| Post media | Platform variants via `next/image` with `sizes`. A blur-up placeholder (`blurhash`) only when the API provides one, otherwise `--color-surface-sunken`. Media still `scanning` renders a neutral "Processing…" tile. `rejected` media is never shown to anyone but the author, who sees "This image couldn't be published". |
| Aspect ratios | Hero 16:9 (mobile 4:5), destination card 4:3, story card 4:5, post media as uploaded (clamped 4:5 to 1.91:1), avatar 1:1, group cover 3:1 |
| Alt text | Content images: author-provided alt (composer field, required for publish when an image is present, with a helpful default prompt). Decorative placeholders: `alt=""`. |
| Video | Never autoplays with sound. Muted inline preview only when `prefers-reduced-motion` is not set and the card is ≥ 50 % visible. Captions track when provided. |

## 11. Component inventory

**Pkg:** `ui` = `@travelbuddy/ui` (generic, no data fetching, no app imports). `web` = `apps/web/src/components` (cross-feature composites) or `apps/web/src/features/<feature>/components` (feature-owned). **Phase** = the web phase in which the component first ships (brief §31 / 01 §10).

Common state legend used in the tables: **L** loading · **D** disabled · **E** error · **∅** empty.

### 11.1 Primitives (`@travelbuddy/ui`, Phase 1 unless noted)

| Component | Purpose | Variants | States | A11y notes | Used by |
|---|---|---|---|---|---|
| **Button** | Actions | `primary`, `accent`, `secondary`, `outline`, `ghost`, `danger`, `link`; sizes `sm` / `md` / `lg`; `asChild` for links | L (spinner + `aria-busy`, label kept), D | Native `<button>`; `type="button"` default; loading keeps the accessible name | Everywhere |
| **IconButton** | Icon-only action | same variants; `sm` / `md` / `lg` (min 44 px hit area) | L, D | `aria-label` **required** by type; tooltip on hover/focus | Toolbars, cards, nav |
| **Input** | Single-line text | `text`, `email`, `search`, `url`, `number`; with leading/trailing adornment | D, E (`aria-invalid`, red border + icon) | ≥ 16 px font; label always associated via FormField | Forms |
| **Textarea** | Multi-line text | auto-grow (max rows), character counter | D, E | Counter announced politely when within 10 % of the limit | Composer, bio, reports |
| **Select** | Choose one from few | native (mobile-friendly) and Radix custom | D, E | Native on touch devices | Settings, filters |
| **Checkbox** | Boolean / multi-select | default, indeterminate | D, E | Radix; label click target | Consent, filters |
| **Switch** | Immediate on/off setting | `sm` / `md` | D, L (while saving) | `role="switch"`; state announced; never used for actions that need confirmation | Privacy, notification settings |
| **RadioGroup** | One of several | vertical, horizontal, card-style | D, E | Arrow-key navigation (Radix) | Visibility, plan choice, report reasons |
| **Label** | Form label | default, required marker (text "required", not only `*`) | D | `htmlFor` | Forms |
| **FormField** | Label + control + description + error wiring | — | E | Generates IDs; `aria-describedby` for help and error; error text has an icon | All forms (RHF integration) |
| **Card** | Content container | `flat`, `elevated`, `interactive` (whole-card link via stretched link) | L (skeleton slot) | Interactive cards keep one primary link; secondary actions remain separately focusable | Most lists |
| **Badge** | Status/metadata label | `neutral`, `primary`, `success`, `warning`, `danger`, `info`, `premium`, `mock` | — | Text always present (not colour-only) | Status, counts |
| **Chip / ToggleChip** | Filter or tag; toggleable | `static`, `toggle` (pressed), removable | D | ToggleChip = `aria-pressed`; removable has a labelled remove button | Interests, filters, tags |
| **Avatar** | User image | `xs` 24 → `xl` 96; status ring (premium, current) | L (initials until loaded) | `alt` = display name, or `""` when the name is adjacent | Everywhere |
| **AvatarGroup** | Stacked avatars | max N + "+k" | — | "+k" has a text equivalent ("and 5 others") | Groups, reactions |
| **Skeleton** | Loading placeholder | `text`, `circle`, `rect`; shimmer | — | `aria-hidden`; the container has `aria-busy="true"` and an SR-only "Loading…" | All async views |
| **Spinner** | Short indeterminate wait (< 1 s expected) | `sm` / `md` | — | `role="status"` + label | Buttons, inline saves |
| **Tabs** | Switch views in place | `underline`, `pill`; scrollable | D (tab) | Radix tabs; can be URL-synced (then rendered as links with `aria-current`) | Feed tabs, group detail, challenge dashboard |
| **Dialog** | Modal task | `sm` / `md` / `lg`; `alert` (confirm destructive) | L | Focus trap, `Esc`, labelled by title, described by body; `AlertDialog` for destructive actions | Report, confirmations |
| **Sheet / Drawer** | Side or bottom panel | sides `start`, `end`, `bottom`; full-screen on mobile | L | Same as Dialog; `start`/`end` follow `dir` | Mobile nav, filters, assistant, composer (mobile) |
| **DropdownMenu** | Action menu | with icons, separators, destructive item, radio/checkbox items | D (item) | Radix menu semantics; typeahead | Post "…" menu, avatar menu |
| **Popover** | Non-modal rich content | — | — | Radix; focus moves in, returns on close | Date pickers, reaction picker |
| **Tooltip** | Supplementary label | — | — | Shows on focus and hover; never the only source of required info; dismissible with `Esc` (WCAG 1.4.13) | IconButton, rail nav |
| **Toast** | Transient feedback | `success`, `error`, `info`, with action ("Undo", "Retry") | — | `role="status"` (polite) / `alert` for errors; ≥ 6 s, pause on hover/focus; never the only place an error is reported | Mutations |
| **Progress** | Determinate progress | linear, circular; with label | — | `role="progressbar"` with `aria-valuenow` | Uploads, onboarding, audio |
| **Separator** | Visual division | horizontal, vertical | — | `role="separator"` only when semantic, else decorative | Menus, lists |
| **VisuallyHidden** | SR-only text | — | — | — | Labels, live regions |
| **Container** | Width + gutter wrapper | `prose`, `default`, `wide`, `full` | — | — | All layouts |
| **EmptyState** | No-content message | `default`, `compact`; illustration slot; primary + secondary actions | — | Heading level configurable to fit the outline | Lists |
| **ErrorState** | Failure message | `inline`, `page`; retry action; reference ID | — | Focus moves to the heading when replacing content; `role="alert"` for inline | All async views |
| **Pagination / LoadMore** | Cursor paging control | `LoadMore` button, `InfiniteSentinel` (IntersectionObserver) + LoadMore fallback | L, D (no more), E (retry) | Infinite scroll always pairs with a visible "Load more" button for keyboard and SR users; new items announced ("10 more posts loaded") | Feed, stories, lists |
| **Combobox / Autocomplete** | Searchable select | single, multi; async options; grouped results | L, E, ∅ ("No matches") | WAI-ARIA combobox pattern (`aria-expanded`, `aria-activedescendant`); debounced 250 ms; results count announced | DestinationAutocomplete, user pickers |
| **DatePicker / DateRangePicker** *(added)* | Pick travel dates | single, range; min/max | D, E | Keyboard grid navigation; typed input alternative; locale-aware first day of week | Trips, groups, discovery filters (Phase 4) |

### 11.2 Composites (`apps/web`)

| Component | Purpose | Variants | States | A11y notes | Used by | Phase |
|---|---|---|---|---|---|---|
| **SiteHeader** | Public header | `transparent` (over hero) → `solid` after scroll; mobile with menu Sheet | — | Landmark `<header>`; nav `aria-label="Main"`; transparent mode keeps ≥ 4.5:1 via hero scrim | Public pages | 1 |
| **SiteFooter** | Public footer | 4-col / 2-col / accordion | — | `<footer>`; `<nav aria-label="Footer">` | Public pages | 1 |
| **LocaleSwitcher** | Change locale | menu (app), list of links (public, works without JS) | — | Each option labelled in its own language with `lang` attribute ("Português (Brasil)") | Header, footer, settings | 1 |
| **ThemeToggle** | Light/Dark/System | icon menu, inline radio (settings) | — | Radio menu semantics | Header, avatar menu, settings | 1 |
| **TravelerSidebar** | App primary nav | `expanded`, `rail`, `overlay` | — | `<nav aria-label="Primary">`; `aria-current="page"`; badge counts in the accessible name | Traveler shell | 1 |
| **MobileBottomNav** | Mobile primary nav (Home, Explore, Trips, Messages, Profile) | hidden inside message threads and full-screen sheets | — | 44 px targets; labels always visible; respects safe-area insets | Traveler shell | 1 |
| **AdminSidebar** *(added)* | Admin nav filtered by permissions | expanded, drawer | — | as TravelerSidebar | Admin shell | 1 (shell) / 8 |
| **EnvironmentBanner** | Shows "Mock data" / "Staging" | `mock` (info), `staging` (warning) | — | In normal flow; `role="note"`; never dismissible in mock mode | All layouts | 1 |
| **OnlineOnlyBadge** *(added, OFF-003)* | Marks online-only features when offline | — | — | Text, not only an icon | Feed, Companions, Messages, Assistant | 3 |
| **DestinationCard** | Destination teaser | `default` (4:3), `compact` (row), `feature` (large) | L (skeleton) | Whole-card link; name is the link text; country as secondary text | Home, directory, country page, search | 2 |
| **DestinationHero** | Destination page header | with photo / with placeholder | — | `h1` = localized name; photo credit visible | Destination & country pages | 2 |
| **DestinationPlaceholder** | Deterministic branded artwork (§10) | aspect ratio prop, dark palette | — | Pattern `aria-hidden` | Any missing destination image | 1 |
| **StoryCard** | Public story teaser | `vertical` (4:5), `horizontal` | L | Title link; author and destination as text | Home, stories index, destination page | 2 |
| **PostCard** | Feed post | `feed`, `detail`, `compact`; media grid 1–4 | L, E (media), "Processing" media | `<article>` with `aria-labelledby` author + time; actions labelled ("Like, 12 likes"); content `lang` = post language; "Edited" indicator (POST-007) | Feed, profile, post detail | 3 |
| **PostComposer** | Create/edit post (POST-001/002/008) | `modal`, `page`, `sheet` (mobile); kinds: text, photo, video, story, recommendation, review (rating), tip, itinerary summary, experience | L (publishing), D (until valid), E, draft restored | Every field labelled; location-precision and visibility explained in plain language; alt text required for images | `/posts/new`, edit | 3 |
| **MediaUploader** | Presigned upload flow | drag-and-drop (desktop), picker + camera (mobile); image/video | L (per-file progress), E (retry, too large, unsupported type) | Progress per file announced; remove buttons labelled with the file name | Composer, profile photo, group cover, DM | 3 |
| **ReactionBar** | Like / love / helpful / wow, comment, bookmark, share (POST-005). **One reaction per user per post, changeable**: `POST /v1/posts/{id}/reactions {reaction}` sets or replaces it, `DELETE /v1/posts/{id}/reactions/me` clears it | compact, full; reaction picker popover | Optimistic, E (rollback + toast) | Picker is a RadioGroup-like menu (one selected); the current reaction is announced ("Your reaction: Helpful"); counts in labels; share only for public posts | PostCard, StoryCard (gate→login) | 3 |
| **ReportDialog** | Report content or user (SAFE-002) | targets: post, comment, user, message, group, challenge | L, E, success | Reasons as RadioGroup; free text optional; confirms with the next steps; never paywalled | All UGC surfaces | 3 |
| **FeedTabs** | For You / Nearby / Following / Destinations (FEED-002) | URL-synced | — | Tabs as links (`?tab=`), `aria-current` | `/feed` | 3 |
| **LocationFilterBar** | Feed location context and filters (FEED-003, LOC-002) | collapsed summary chip ("Rio de Janeiro · Selected"), expanded sheet; radius for Nearby | L (resolving), E (permission denied → fallback) | "Use my location" is an explicit button; explains that location is not stored (LOC-003) | `/feed` | 3 |
| **DestinationAutocomplete** | Search destinations (DEST-001) | inline (hero), field (forms), full-screen (mobile) | L, ∅, E | Combobox pattern; shows hierarchy ("Copacabana · Rio de Janeiro, Brazil") | Hero, onboarding, composer, filters, trips, groups | 2 |
| **SaveButton** *(added)* | Save destination/place/tour from a public page | icon, labelled | Optimistic, gate→login | `aria-pressed` | Destination page, places | 3 |
| **TravelerCard** | Discovery result (DISC-004/005) | `grid`, `list` | L | Area label only (city/neighborhood), shared interests as chips, date overlap as "Dates overlap · N days"; never distance or coordinates | `/companions` | 4 |
| **ConnectionButton** | Relationship action per CONN-001 state | none → "Connect", pending-out → "Requested" (cancel), pending-in → "Accept/Decline", connected → menu, restricted → hidden | L, D+why (cooldown, restricted) | State text, not only colour; menus labelled | TravelerCard, profiles, member list | 4 |
| **SafetyGuidance** *(added, SAFE-008)* | Safety tips panel | `inline`, `dialog` (first enable) | — | Text from doc 08 §7; never claims safety | Discovery opt-in, first connection accepted | 4 |
| **DiscoveryStatusIndicator** *(added, T-LOC-09)* | Persistent "Visible in Lisbon until 18:00" indicator | top-bar chip, settings row | — | Live region on expiry | Traveler shell | 4 |
| **ConversationList** | Conversation index | with search, unread badges, muted icon | L, ∅, E | `role="list"`; each item announces unread count and last activity | `/messages` | 4 |
| **MessageThread** | Message history | DM, group; day separators; reply previews; pinned bar (group) | L (older pages), E (failed message with retry), gap-sync indicator | `role="log"` with polite announcements for new messages; read/delivery status as text for SR | Messages, group chat | 4 |
| **MessageComposer** | Write message | text + photo; reply-to; mention picker (group) | D (blocked / restricted / no connection), sending, failed | Enter to send, Shift+Enter newline (configurable); attachment button labelled | Messages, group chat | 4 |
| **TypingIndicator** | Ephemeral typing state (DM-008) | — | — | Visually animated; SR announcement throttled (once per 10 s) | MessageThread | 4 |
| **NotificationItem / NotificationList** *(added)* | Notification centre (NOTIF-001) | grouped by day | L, ∅ | Unread state as text | `/notifications`, bell popover | 4 |
| **GroupCard** | Group teaser | `mine`, `invitation`, `discover` | L | Name link; privacy shown as text ("Private · Invite only") | `/groups*` | 5 |
| **GroupHeader** | Group detail header + tabs | member / admin (settings link) | L | `h1` group name; tabs as links | `/groups/[id]/*` | 5 |
| **MemberList** | Members with roles | admin actions variant | L, ∅ | Role badges as text; admin actions in a menu per member | Members tab, settings | 5 |
| **InvitationManager** *(added, GRP-005)* | Direct invites + link invites (max uses, expiry, revoke) | — | L, E (capacity, `entitlement_required` after lapse) | Copy-link confirms via toast and live region | Group settings | 5 |
| **EntitlementGate** | Renders children, upsell or lapse notice by entitlement (07 §3) | `upsell`, `lapsed` (owner grace countdown), `quota` (meter) | L | Never hides safety actions; upsell explains what unlocks | Group create, challenges, premium guides, AI quotas | 5 |
| **PricingTable** | Plans from `GET /v1/billing/products?platform=web` | monthly/annual toggle; current plan marker; store-subscription notice | L, E, "Checkout unavailable in this environment" (D) | Prices formatted per locale and currency from Stripe Price data; no hard-coded prices | `/pricing`, `/membership` | 2 (display) / 5 |
| **ChallengeCard** | Challenge teaser (CHAL-003) | `active`, `upcoming` (title + start only), `completed` (winner) | L | Status as text; countdown with an accessible static time | Challenge dashboard | 7 |
| **RiddleSubmission** | Answer form (CHAL-004/005) | individual, team (captain only) | D+why (not active, attempts exhausted, cooldown, not captain), L, E | Attempts left from server; result announced as "Correct" / "Not correct"; nothing more | Challenge detail | 7 |
| **HintReveal** *(added)* | Request hint per schedule | locked (unlock time), revealed | D+why | — | Challenge detail | 7 |
| **ChallengeEditor** *(added)* | Create/edit challenge (CHAL-002) | — | L, E (server validation incl. CHAL-013 prohibited rewards) | Answer fields are write-only (never pre-filled from the API) | Challenges tab (admins) | 7 |
| **ItineraryDayList** | Days of a trip | timeline, compact | L, ∅ | Each day a region with a heading (date in the destination time zone) | Trip detail, AI preview, group itinerary | 6 |
| **ItineraryItem** | Activity row | activity, meal, transit, lodging, note; `unverified` flag; "Estimated" duration/cost | Dragging, saving, conflict (412 → refresh prompt) | **Accessible reorder:** drag handle plus "Move up/Move down" buttons and a "Move to day…" menu; keyboard reorder with Space to lift and Arrow keys, announced via live region | Trip detail | 6 |
| **TripCard** | Trip teaser | upcoming, past, shared | L | Dates in the destination time zone | `/trips`, profile | 6 |
| **ItineraryPreview** *(added, AI-002/004)* | AI result before saving | with regenerate/modify/save/share | L (streaming), E (`ai_unavailable`, `quota_exceeded`) | Labels unverified items and estimates; source attribution; no hours or prices unless grounded with freshness | Assistant | 6 |
| **AssistantPanel** *(added)* | Chat UI | drawer, page | L (stream), E | `role="log"`; stop-generation button | `/assistant`, global drawer | 6 |
| **MapView** | MapLibre map (ADR-0014) | `explore` (viewport loading), `static` (destination), `itinerary` (route) | L (lazy chunk), E (style failed → list fallback), "Development map" label | Map is supplementary: every marker is also in an adjacent list; keyboard-operable zoom controls; `aria-label` summary | Explore, destination, trip, tour | 2 (static) / 6 |
| **PlaceMarker / Cluster** | Map markers and clusters | by category (restaurant, nature, museum, beach, activity, saved) | selected, hovered | Each marker focusable via the linked list item; cluster announces count | MapView | 6 |
| **AudioPlayer** | Tour playback | mini (persistent), full | L, E | Native-like controls with labels; speed 0.75–2×; keyboard shortcuts documented; transcript link | `/tours/[id]` | 6 |
| **TourStopList** | Ordered tour stops | with "Play this stop" (manual fallback when geofencing is unavailable) | L | Current stop `aria-current` | `/tours/[id]` | 6 |
| **OnboardingStepper** | Seven-step onboarding (PROF-001) | progress bar + step title; skippable steps | L (saving), E | "Step 3 of 7" in text; Skip is a real button; focus moves to the step heading | `/onboarding` | 3 |
| **AdminDataTable** | Sortable, filterable server-paged table | selectable rows, column visibility, density | L, ∅, E | `<table>` semantics, sortable headers with `aria-sort`; row actions in menus | Admin lists | 8 |
| **MetricTile** | KPI tile | value + delta + sparkline; `unavailable` | L, E ("Metric unavailable"; never a fabricated number) | Delta direction as text ("up 4 %"); chart has a table alternative | `/admin` | 8 |
| **ModerationActionDialog** | Apply an action with reason code (ADM-002) | remove, limit, warn, restrict, suspend, ban, reinstate | L, E | Reason required; preview of user-facing notice; destructive confirm | Reports, users, groups | 8 |
| **AuditLogTable** | Append-only audit viewer | filter by actor, action, resource, date | L, ∅ | Monospace IDs copyable | `/admin/audit`, user detail | 8 |
| **PiiReveal** *(added, ADM-003)* | Field-level reveal requiring a justification | — | L, D (no `USERS_READ_PII`) | Reason input labelled; reveal is audited | User detail | 8 |

## 12. Governance

* New primitives go to `@travelbuddy/ui` only when two or more features need them. Feature composites live in `apps/web/src/features/<feature>/components`.
* Every `ui` component ships with a unit test (render, keyboard, a11y via `axe`), and a story-style fixture page under `/dev/ui` (dev builds only) until Storybook is justified.
* A visual change to a token is a design review item. Contrast values in §2.2 are re-measured by a unit test that parses `tokens.css`.

## 13. Open questions

| # | Question | Proposed resolution |
|---|---|---|
| Q1 | The `ui` primitives are web-only, but the token TS export is meant for React Native (01 §3). The mobile stream now lives at `mobile/` as a standalone project (ADR-0009). | Keep `tokens.ts` dependency-free so `mobile/` can copy or depend on it when it joins the workspace. Placeholder algorithm (§10) to be shared then. |
| Q2 | The CSP for the inline theme script needs a hash allowance. | 08 (web security) to include the hash in the CSP policy. |
| Q3 | Entitlement keys used by EntitlementGate follow [07 §3](../07-subscription-entitlement-policy.md#3-features-and-quotas) (`groups.create`, `challenges.create`, `guides.premium`, `audio_tours.premium`, `ai.trip_replan`; quotas `ai.itinerary_generations`, `offline.packages`, `groups.owned`). [Web 03 §2](03-roles-permissions.md#2-entitlement-feature-keys) uses different keys and numbers. | 03 to align with 07 (07 is normative for the backend). |
