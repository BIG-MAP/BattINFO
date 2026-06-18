# BattINFO — Visual Identity

> The semantic data layer for battery technology.

This is the canonical brand reference for BattINFO. It is the single source of
truth for the docs site and any future web property. Color/spacing/type values
live as code in [`tokens.css`](tokens.css); this file explains *how* to use them.

Asset pack version: **v1.0**.

---

## 1. The mark

The symbol is a **battery outline containing a three-node line graph** — a data
signal read out of a cell. It encodes the product: structured data about
batteries.

| Variant | File | When to use |
|---------|------|-------------|
| Primary symbol (full color) | [`assets/icon/icon.svg`](assets/icon/icon.svg) | App mark, avatar, favicon source |
| Monochrome (Ink) | [`assets/icon/icon-mono.svg`](assets/icon/icon-mono.svg) | Single-color / engraving / low-color |
| Reversed | [`assets/icon/icon-reversed.svg`](assets/icon/icon-reversed.svg) | White battery + teal graph on dark |
| Knockout | [`assets/icon/icon-knockout.svg`](assets/icon/icon-knockout.svg) | All-white over photos / colored fills |

### Lockups

| Variant | File | When to use |
|---------|------|-------------|
| Horizontal | [`assets/logo/logo-horizontal.svg`](assets/logo/logo-horizontal.svg) | Primary lockup — symbol + wordmark side by side |
| Horizontal on dark | [`assets/logo/logo-horizontal-on-dark.svg`](assets/logo/logo-horizontal-on-dark.svg) | Same, for dark backgrounds |
| Stacked | [`assets/logo/logo-stacked.svg`](assets/logo/logo-stacked.svg) | Vertical — symbol above centered wordmark |

The wordmark is **"Batt"** in Ink + **"INFO"** in Signal Teal, set in
**Plus Jakarta Sans 700**.

> ⚠ **Before external distribution, outline the wordmark.** The lockup SVGs render
> the text via an embedded Google Fonts `@import`, which only works online. For
> print, email signatures, or offline use, open the lockup in Figma/Illustrator
> and run **Type → Create Outlines** so the text becomes vector paths. The
> `icon*.svg` files are pure geometry and need no outlining.

### Clear space & minimum sizes

- **Clear space:** keep clear space ≥ the height of the symbol's terminal cap on all sides.
- **Minimum sizes:** full lockup **120px** wide · symbol alone **24px** · favicon **16px**.

---

## 2. Color

Full values and CSS variables are in [`tokens.css`](tokens.css). Summary:

### Brand
| Token | Hex | Role |
|-------|-----|------|
| Ink | `#102A43` | Battery, "Batt", primary text, headers |
| Signal Teal 500 | `#12A394` | Graph, "INFO", brand fills — **large display only** |
| Signal Teal 700 | `#0C7A6E` | Teal *text*, links, buttons — AA-safe (5.2:1) |
| Favicon Teal | `#19C2AE` | Brighter teal, **≤32px legibility only** |

> **Critical rule:** Teal 500 fails AA as body text. For any teal text, link, or
> button use **Teal 700**. Reserve Teal 500 for large graphics and fills.

### Neutrals & surfaces
| Token | Hex | Role |
|-------|-----|------|
| Slate 700 | `#2E4257` | Secondary text |
| Muted | `#5A6570` | Tertiary text / captions |
| Surface | `#FFFFFF` | Cards |
| Paper | `#F3F2EE` | Page background |
| Border | `#E7E5DF` | Hairlines |
| Tint | `#E4F4F1` | Teal wash, tags |

A surface card pairs Paper-tinted background with a hairline border and a 14px radius.

### Semantic states (all AA-verified on white, also legible as white-on-solid)
| State | Solid | Tint | Contrast |
|-------|-------|------|----------|
| Success | `#178050` | `#E4F4EC` | 4.95 |
| Warning | `#946007` | `#FBF0DA` | 5.34 |
| Error | `#C8372D` | `#FBE7E4` | 5.20 |
| Info | `#2563B8` | `#E5EEFA` | 5.91 |

Pair each solid with its tint for banners, badges, and inline alerts.

### Interaction
Primary button hover `#1D3A57` · active `#0A1B2C` · disabled surface `#C2C8CE` ·
2px focus ring `#0C7A6E`.

---

## 3. Typography

Two typefaces, both on Google Fonts:

- **Plus Jakarta Sans** — UI, headings, body, wordmark.
- **JetBrains Mono** — code, captions/labels, data values, hex codes.

### Type scale
| Style | Size | Weight | Tracking | Line-height |
|-------|------|--------|----------|-------------|
| Display | 3.5rem | 800 | −2.5% | 1.05 |
| Heading 1 | 2.5rem | 700 | −2% | 1.1 |
| Heading 2 | 1.5rem | 700 | — | 1.25 |
| Body large | 1.125rem | 500 | — | 1.55 |
| Body | 1rem | 500 | — | 1.6 |
| Caption / Label | 0.75rem | mono | — | uppercase, letter-spacing 0.1em |

---

## 4. Spacing, radius, elevation

- **Spacing** is on a 4px base: xs 4 · sm 8 · md 16 · lg 24 · xl 48.
- **Radius:** controls 6px · buttons 10px · cards 14px.
- **Elevation:** sm `0 1px 3px rgba(20,30,40,0.08)` · md `0 6px 20px rgba(20,30,40,0.12)`.

---

## 5. Favicons, app icons & social

| File | Use |
|------|-----|
| [`assets/favicon/favicon.svg`](assets/favicon/favicon.svg) | Browser favicon (rounded Ink tile, brighter teal graph) |
| `favicon-16/32/48.png` | PNG fallbacks |
| `apple-touch-icon-180.png` | iOS home-screen icon |
| `app-icon-512.png` | PWA / Android maskable source |
| [`assets/social/og-image.png`](assets/social/og-image.png) | 1200×630 Open Graph / social share card |

### HTML `<head>` snippet
```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon-180.png">
<meta property="og:image" content="/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
```

---

## 6. Using the tokens

Import the canonical token file rather than re-typing hex values:

```css
@import url("../../../brand/tokens.css");   /* path relative to your stylesheet */

a            { color: var(--bi-teal-700); }
.card        { background: var(--bi-surface); border: 1px solid var(--bi-border);
               border-radius: var(--bi-radius-card); box-shadow: var(--bi-shadow-sm); }
body         { font-family: var(--bi-font); color: var(--bi-ink);
               background: var(--bi-paper); }
code, pre    { font-family: var(--bi-font-mono); }
```

Web fonts (add to the page `<head>`):
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```
