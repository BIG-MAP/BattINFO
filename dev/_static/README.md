# BattINFO — Brand assets

Canonical home of the BattINFO visual identity. Single source of truth for the
docs site and the future web property.

- **[`BRAND.md`](BRAND.md)** — the visual identity guide (logo, color, type, usage).
- **[`tokens.css`](tokens.css)** — design tokens as CSS variables. Import this; don't fork the values.
- **`assets/`** — logo, icon, favicon, and social image files.

```
brand/
├── BRAND.md            visual identity guide (read this first)
├── tokens.css          design tokens — single source of truth
└── assets/
    ├── logo/           horizontal, horizontal-on-dark, stacked lockups
    ├── icon/           symbol: full-color, mono, reversed, knockout
    ├── favicon/        favicon.svg + PNG fallbacks, apple-touch, app-icon-512
    └── social/         og-image.png (1200×630)
```

## Consumers

| Consumer | How it uses these assets |
|----------|--------------------------|
| **Sphinx docs** (`docs/`) | `conf.py` points `html_logo`/`html_favicon` here; `_static/css/custom.css` imports `tokens.css` and maps the values onto pydata-sheet theme variables. |
| **Future web** (`web/`) | Imports `tokens.css` directly and serves `assets/favicon/*` + `assets/social/og-image.png`. |

When the identity changes, edit `tokens.css` / `assets/` **here** and let consumers
pick up the change — never hardcode brand values downstream.

Asset pack version: **v1.0**.
