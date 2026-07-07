# battinfo.org — website

The public landing pad and documentation site for **BattINFO**, the semantic
data layer for battery technology. Deployed at <https://battinfo.org>.

This is a self-contained Next.js app living inside the BattINFO monorepo. It is
the only thing in this directory; it does **not** import from or modify the
Python package, ontology, schemas, or any other part of the repo. Content that
needs to stay in sync with the ontology/schemas (term reference, schema browser)
is pulled in at build time via an explicit sync step (see "Content sources"
below) — never by reaching across the repo at runtime.

## Develop

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

## Build

```bash
npm run build
npm run start
```

## Deploy (Vercel)

Create a **separate Vercel project** for this site and set:

- **Root Directory:** `web`
- **Domain:** `battinfo.org`
- **Ignored Build Step:** skip builds when nothing under `web/` changed, e.g.
  `git diff --quiet HEAD^ HEAD -- .` — so ontology/package commits don't trigger
  a site rebuild.

Keeping the Vercel root scoped to `web/` is what keeps the monorepo split-able
later: the site is a pure subdirectory consumer.

## Content sources

The site is a presentation layer. The sources of truth stay where they live:

| On the site | Source of truth | How it gets here |
|---|---|---|
| Term / IRI reference | `battinfo.ttl`, `assets/ontology/` | build-time sync script (TODO) |
| Schema browser | `assets/schemas/*.json` | build-time sync script (TODO) |
| Examples (flagship record) | `examples/cell-spec/A123__ANR26650M1-B.json` | `npm run sync:examples` → `lib/examples.generated.ts` (committed) |

```bash
npm run sync:examples   # regenerate lib/examples.generated.ts from examples/**
```

`lib/examples.generated.ts` is generated and **committed** (so the Vercel build,
scoped to `web/`, never reaches outside it). CI should re-run the sync and fail
on a dirty diff. The remaining inline fixtures under `lib/` are clearly marked
teasers; see `docs/CONTENT-MODEL.md` §4 for what is and isn't synced yet.
Resolution of `w3id.org/battinfo/` IRIs stays on w3id.org — this site never
serves as the IRI resolver.

## Status

Early draft scaffold. Landing, docs index, examples, and an in-browser
structural validator are stubbed out and runnable. Not production content.
