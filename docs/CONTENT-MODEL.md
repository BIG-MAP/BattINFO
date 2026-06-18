# Content model — website vs. developer reference

BattINFO has **two documentation surfaces**. They are not duplicates; they have
distinct jobs and distinct audiences. This document is the contract that keeps
them from drifting into each other. Read it before adding or moving content.

## The two surfaces

| | **Website** (`web/`, battinfo.org) | **Developer reference** (`docs/`, Sphinx) |
|---|---|---|
| **Job** | The front door: *why* and *try* | The manual: *how* and *reference* |
| **Audience** | Everyone — newcomers, evaluators, casual users (the majority) | Developers building with the library (a minority, but high-value) |
| **Tone** | Curated, marketing-grade, self-sufficient for non-developers | Exhaustive, precise, assumes you already know *why* |
| **Maintenance** | Hand-authored | Largely generated from code (docstrings, notebooks, schemas); versioned with releases |

## The rule

> **Web owns "why" and "try." Sphinx owns "how" and "reference."**
> Each surface links to the other at the handoff; **neither re-explains the
> other's territory.** Every piece of content has exactly **one canonical owner**.

## Ownership matrix

| Content | Canonical owner | The other surface |
|---|---|---|
| Positioning, value proposition | **Web** | — |
| Concepts / "why" (data federation, semantic-layer overview, what BattINFO is) | **Web** | Sphinx keeps a short stub that links to the web page; it does not re-explain |
| Interactive tools (Validate, Convert) | **Web** | Sphinx links to them (navbar + prose) |
| Getting-started teaser | **Web** | hands off to Sphinx for the full quickstart |
| Full quickstart, tutorials, notebooks | **Sphinx** | Web links in |
| Python API, CLI, JSON Schemas, validation contract, identifier policy, ontology architecture | **Sphinx** | Web links in ("Developer reference →"); **never copies** |

When in doubt: *is this telling someone **why** to care or letting them **try**
something?* → web. *Is it the precise **how** a developer needs?* → Sphinx.

## Anti-drift mechanisms

These are what make the boundary survive growth. Keep them working.

1. **One canonical owner per item** (the matrix above). This is the structural
   rule; everything else supports it.
2. **Link, never copy reference.** API/CLI/schema content appears in web *only*
   as outbound links to the developer reference (`site.reference` in
   `web/lib/site.ts`). Reference content rots when duplicated, so it is
   duplicated nowhere.
3. **Concept stubs, not copies.** A concept lives fully on the web. If the
   reference needs it, it carries a short framing summary plus a link out — see
   `docs/data-federation.md` for the pattern.
4. **Single-source example content.** The canonical battery records live in
   `examples/**` (e.g. `examples/cell-spec/A123__ANR26650M1-B.json`, the flagship
   cell both surfaces feature).
   - **Sphinx** should render full examples via `literalinclude` from
     `examples/**`, not by re-typing JSON.
   - **Web** keeps short, curated *teasers* inline (`web/lib/examples.ts`), but
     full example content must come from `examples/**`. The intended end state is
     a build-time sync (see below). Teasers may be subsets; they must not invent
     fields or shapes that disagree with the canonical record.
5. **Written rule + CI link-check.** This file is the rule. Both builds should
   run a link checker in CI (`sphinx-build -b linkcheck` for docs; a link
   checker for the Next build) so cross-surface links can't silently break.

## Build-time example sync (implemented)

`web/lib/examples.ts` is consumed by client components, so the web app cannot
read `examples/**` at runtime. The robust pattern is **vendored-with-sync**, and
it is wired up:

- `web/scripts/sync-examples.mjs` reads the canonical record from `examples/**`
  and writes a generated module (`web/lib/examples.generated.ts`), **committed**
  to the repo so the Vercel build stays self-contained. Output is byte-stable
  (idempotent), so the drift check is reliable.
- `npm run sync:examples` regenerates it. CI should run it and fail on a dirty
  diff: `npm run sync:examples && git diff --exit-code lib/examples.generated.ts`.
- The Examples page (`web/app/examples/page.tsx`) renders `cellSpecInput` from
  the generated module, so its values can never drift from the canonical record.

Two things still ride on inline teasers, by necessity:

1. **JSON-LD** (`cellSpecJsonLd`) is illustrative until the Python transform
   (`battinfo.jsonld.record_to_jsonld`) can emit canonical JSON-LD files into
   `examples/**`; once it can, add them to the sync.
2. **`toolDemoInput`** feeds the Validate/Convert demos, whose simplified
   in-browser logic (`lib/validate.ts`, `lib/convert.ts`) still expects the
   pre-migration `product`/`specs` shape. **Follow-up:** migrate those two files
   to the canonical `cell_spec`/`properties` shape, then point the demos at
   `cellSpecInput` and delete `toolDemoInput`.

## Naming & handoff

- The website is titled **"Documentation"** for users; the Sphinx site is the
  **"Developer reference."** Distinct names so users know which they want.
- **Web → reference:** `site.reference` (currently the GitHub `docs/` tree; point
  it at `https://docs.battinfo.org` once Sphinx is deployed) with a prominent
  callout on the web `/docs` page.
- **Reference → web:** the Sphinx navbar carries Home / Validate / Convert links
  back to battinfo.org (`external_links` in `docs/conf.py`).
- Both surfaces share the brand pack (`brand/`), so they read as one system.

## Considered and rejected

Collapsing both onto one platform (Next.js + MDX, or Docusaurus). It would
discard Sphinx's autodoc-from-docstrings and executable notebooks — the exact
machinery that keeps a developer reference correct for free. Two best-in-class
tools with a disciplined seam beats one tool doing both jobs adequately.
