# BattINFO — Brand Asset Pack v1.1

The semantic data layer for battery technology.

## ⭐ Start here (front-end / coding agent)

1. **`AGENTS.md`** — implementation rules the coding agent MUST follow.
   Read it first; it explains the light/dark failures and how to avoid them.
2. **`tokens.css`** — the dual-mode design-token system. Import once at the app
   root; build every surface from its `--bi-*` semantic tokens. This is the
   fix for the light/dark coherency problems: one contract, two value sets,
   all contrast-verified.

```css
@import "./brand-assets/tokens.css";
```
```html
<html data-theme="light"> … </html>   <!-- or data-theme="dark" -->
```

## Files

| File | Use |
|------|-----|
| `AGENTS.md` | **Front-end implementation rules — read first.** |
| `tokens.css` | **Dual-mode design tokens (light + dark). Import at app root.** |
| `icon.svg` | Primary symbol (full color). App mark, avatar, favicon source. |
| `icon-mono.svg` | Single-color Ink version. Faxes, engraving, low-color contexts. |
| `icon-reversed.svg` | White battery + teal graph, for dark backgrounds. |
| `icon-knockout.svg` | All-white, for photos / colored fills. |
| `favicon.svg` | 32×32 rounded-square app tile (brighter teal for small-size legibility). |
| `logo-horizontal.svg` | Primary lockup: symbol + wordmark, side by side. |
| `logo-horizontal-on-dark.svg` | Horizontal lockup for dark backgrounds. |
| `logo-stacked.svg` | Vertical lockup: symbol above centered wordmark. |
| `favicon.svg` `favicon-16/32/48.png` | Browser favicon (SVG + PNG fallbacks). |
| `apple-touch-icon-180.png` | iOS home-screen icon. |
| `app-icon-512.png` | PWA / Android maskable source. |
| `og-image.png` | 1200×630 social / Open Graph share card. |

## HTML head snippet

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon-180.png">
<meta property="og:image" content="/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
```

## Colors — quick reference

Full token definitions (light **and** dark values) live in `tokens.css`.
Use the semantic `--bi-*` tokens in code, never these raw hexes directly.

**Light mode**
- **Ink** `#102A43` — primary text, "Batt", battery outline
- **Signal Teal 500** `#12A394` — brand fills, "INFO", ≥24px display only
- **Signal Teal 700** `#0C7A6E` — teal text, links, buttons (AA 5.2:1)

**Dark mode** (the part the code agent kept getting wrong)
- Base `#0B1622` · Surface `#13212F` · Inset `#0E1B27` (elevate = lighter)
- Primary text `#EAF1F6` — **near-white, NOT ink navy** (ink navy = 1.24:1, invisible)
- Brand fill `#2DD4BF` · Teal text/links `#2DCAB6` (AA 8.9:1) — teal brightens on dark
- Primary button = teal fill w/ dark ink text (an ink button disappears on dark)

## Semantic state colors (all AA-verified on white)
- **Success** `#178050` (4.95) · tint `#E4F4EC`
- **Warning** `#946007` (5.34) · tint `#FBF0DA`
- **Error** `#C8372D` (5.20) · tint `#FBE7E4`
- **Info** `#2563B8` (5.91) · tint `#E5EEFA`

## ⚠ Before external distribution — outline the wordmark

The lockup SVGs style the wordmark with **inline font attributes** targeting
**Plus Jakarta Sans (700)** with a `system-ui → sans-serif` fallback stack, so
they always render at the correct size and weight — even when embedded via
`<img>` (which blocks external webfont loading) or opened offline. The fallback
is a close geometric sans, but it is not the exact brand face.

For pixel-exact brand rendering in **print, email signatures, or any context
where Plus Jakarta Sans may be absent**, open a lockup in Figma/Illustrator and
**Type → Create Outlines** (~30s) so the wordmark becomes vector paths with no
font dependency at all.

The `icon*.svg` files are pure geometry — resolution-independent, no font, no
outlining needed.

## Minimum sizes
- Full lockup: 120px wide
- Symbol alone: 24px
- Favicon: 16px

## Clear space
Keep clear space ≥ the height of the symbol's terminal cap on all sides.
