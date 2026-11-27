# BattINFO — Front-End Implementation Rules (for the coding agent)

**Read this before writing or changing any UI.** The design system lives in
`brand-assets/tokens.css`. It is the single source of truth. Import it once at
the app root and build everything from the **semantic tokens** it defines.

```css
@import "./brand-assets/tokens.css";
```

Theme is controlled by ONE attribute on `<html>`:
`data-theme="light"` or `data-theme="dark"`. Toggle that attribute only — never
restyle components per-theme by hand.

---

## The 10 hard rules

1. **Only ever use `--bi-*` semantic tokens in components.** Never a raw hex,
   never `rgb()`, never a `--raw-*` primitive. If you need a value that doesn't
   exist as a token, add a semantic token to `tokens.css` (with a light AND a
   dark value) — do not inline it.

2. **Text color is always a `--bi-text-*` token — NEVER a brand color and NEVER
   the ink navy in dark mode.** The washed-out hero happened because ink navy
   (`#102A43`) was used for text on a dark background (1.24:1 — invisible). In
   dark mode `--bi-text-primary` is near-white; the tokens already handle this.

3. **Teal is not one color.** Use `--bi-brand` for FILLS and large display type
   (≥24px) only. Use `--bi-brand-text` for links, small labels, and any teal
   text — it is the AA-safe shade and it automatically brightens in dark mode.
   Never set `--bi-brand` (`#12A394` / `#2DD4BF`) as small text.

4. **Elevate surfaces by getting LIGHTER in dark mode, not darker.**
   `--bi-bg-base` (darkest) → `--bi-bg-surface` (cards) → `--bi-bg-raised`
   (popovers). Code blocks use `--bi-bg-inset` (recedes). Do not paint cards
   the same color as the page.

5. **No large gradients on hero/section backgrounds.** The muddy gray gradient
   in the dark hero is the worst offender. Use a solid `--bi-bg-base`, or at
   most a very subtle radial wash at ≤8% opacity of `--bi-brand`. Never fade a
   section to a different lightness.

6. **Secondary / ghost buttons MUST have a visible border in both modes**
   (`--bi-border-strong`). Use the `.bi-btn-secondary` recipe. The invisible
   dark-on-dark "Validate a record" button was a borderless ghost on a dark
   surface — never do that.

7. **Primary button differs by mode and the token already encodes it.** Light:
   ink-navy fill, white text. Dark: bright-teal fill, dark-ink text. Use
   `.bi-btn-primary`; do not reuse the light treatment in dark mode (an ink
   button vanishes on a dark page).

8. **Borders come from `--bi-border` (hairlines) or `--bi-border-strong`
   (inputs, ghost buttons).** Don't reach for opacity hacks like
   `rgba(255,255,255,0.1)` — use the tokens so dark and light stay coherent.

9. **State colors (success/warning/error/info) come in pairs:** the solid
   (`--bi-success`) for icon/text, the `-bg` (`--bi-success-bg`) for the
   banner fill. Both are mode-tuned and AA-verified. Never invent status colors.

10. **Focus is always visible:** rely on the global `:focus-visible` rule
    (2px `--bi-focus-ring`). Do not set `outline: none` without an equivalent
    visible replacement.

---

## Component recipes (already in tokens.css)

`.bi-card` · `.bi-code` · `.bi-btn` + `.bi-btn-primary` / `.bi-btn-secondary`
· `.bi-badge` · `.bi-input`

Prefer these classes over re-deriving styles. Extend by composing tokens, not
by overriding with new hexes.

---

## Contrast contract (verified, WCAG 2.1)

Every text/background pair below is measured, not estimated. If you introduce a
new pairing, it must clear **AA (≥4.5 for body, ≥3.0 for ≥24px / UI)**.

| Pair | Light | Dark |
|------|-------|------|
| primary text on base    | 14.6 AAA | 16.0 AAA |
| secondary text on base  | 7.9 AAA  | 9.5 AAA  |
| muted text on base      | 4.7 AA   | 5.1 AA   |
| brand-text (link)       | 5.2 AA   | 8.9 AAA  |
| text-on-brand (button)  | AA       | 8.9 AAA  |

`--bi-brand` as *fill* is fine at any size; as *text* it is large-only in light
and must never be used for body copy — that's what `--bi-brand-text` is for.

---

## QA checklist before you ship a screen

- [ ] Toggle `data-theme` light↔dark — every text string stays readable.
- [ ] No element uses a literal hex or a `--raw-*` token.
- [ ] Cards are visibly distinct from the page in BOTH modes.
- [ ] Every ghost/secondary button has a visible edge in dark mode.
- [ ] No section background fades or gradients between lightness levels.
- [ ] Teal text uses `--bi-brand-text`, not `--bi-brand`.
- [ ] Keyboard focus is visible on every interactive element.

## Logo usage

Use the theme-appropriate asset:
- Light UI → `logo-horizontal.svg` / `icon.svg`
- Dark UI  → `logo-horizontal-on-dark.svg` / `icon-reversed.svg`

Do not recolor the logo with tokens; swap the file. Minimum sizes and clear
space are in `README.md`.
