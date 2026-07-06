# Gold-standard docs & web plan — the publishing journey as the product

Goal: a PhD student or engineer who lands on battinfo.org with a folder of cycler
data should think **"this is valuable"** within 30 seconds and **"that's easy"**
within one page — and actually have published, citable, machine-readable records
within 15 minutes of `pip install`.

"Gold standard for scientific data software" is measured against three bars:

1. **The two human tests** (acceptance criteria at the bottom): the 30-second
   stranger test and the 15-minute publish test.
2. **Diátaxis completeness**: tutorial / how-to / reference / explanation each
   exist, are distinct, and are owned per the content model
   (`docs/internal/CONTENT-MODEL.md` — web owns *why/try*, Sphinx owns
   *how/reference*; that contract stays).
3. **pyOpenSci/JOSS review criteria + FAIR4RS**: statement of need, install,
   examples, API docs, tests, community files, citation, archived releases.

Baseline (audited 2026-07-06, post-0.8-prep): the funnel is *correct* — guides
and snippets execute in CI, the quickstart recipe is seam-tested, errors teach.
What's missing is the *story*: the web hero sells "describe a cell" (authoring-
first) rather than "publish your data" (the actual quick win); the web Validate
tool is a hand-rolled heuristic (`validateCellType`, stale name) rather than the
real schemas; there is no single end-to-end publishing tutorial on either
surface; citation/DOI/trust markers are absent from the front door.

Phase order: A defines the narrative every other phase reuses. B and C can run
in parallel after A. D is the final sweep before announcing.

---

## Phase 0 — Reconcile in-flight work (half a day)

- **0.1** `feat/web-validator` (worktree `BattINFO-web`) is 2 lines ahead of main
  (`web/app/page.tsx`, `web/lib/site.ts` deploy-prep). Merge or discard the
  delta, retire the branch, remove the worktree.
- **0.2** Confirm the web deploy pipeline: `web/vercel.json` exists — verify
  battinfo.org auto-deploys from main and that a preview URL exists for PRs
  (needed by every later phase's review loop).
- **0.3** Fix the live-registry data typo ("molicel inr2170-p45b") before the
  search demo becomes a screenshot.

## Phase A — The story: web front door (2–3 days)

**Goal:** the landing page IS the publishing journey.

- **A.1 Hero rewrite.** Headline on the value ("Your battery data — citable,
  machine-readable, and findable. In 15 minutes."); sub-line naming the three
  payoffs (DOI on Zenodo, EMMO-aligned JSON-LD, findable in the Battery Genome
  registry). The hero code block shows the REAL data-first recipe
  (`ws.convert() → ws.search() → ws.add() → ws.save() → ws.publish()`), not
  model authoring. Single-source it: the snippet is extracted from
  `ws.quickstart()`'s output (or asserted against it in web CI) so it can never
  drift from what the library teaches — the same guard philosophy as Phase 1.
- **A.2 "Publish your data" page (the centerpiece).** A visual pipeline diagram
  — raw cycler files → BDF → linked records (spec/cell/test/dataset) → JSON-LD
  → Zenodo DOI + registry — where each stage expands to the exact code, what it
  produces on disk, and a short "why this stage exists" line. Ends with the two
  handoffs: "full tutorial →" (Sphinx C.1) and "try the validator →" (B.1).
  This page is the answer to "exactly what is the procedure".
- **A.3 Proof strip.** Under the hero: test count (from a build-time badge, not
  hand-edited), CI status, license, current version + changelog link, EU/
  DigiBatt + BIG-MAP affiliation, "cite us" (D.1). Value claims are only
  credible with proof attached.
- **A.4 "Why" page tune-up.** The federation page exists and is good; add the
  90-second version to the homepage (three cards: for you now / for your lab /
  for the field) and link the Battery Genome platform as the payoff.
- **A.5 Navigation reflects the journey.** Nav becomes: Publish · Validate ·
  Convert · Examples · Why · Docs. "Publish" is first.

## Phase B — Real tools in the browser (3–4 days)

**Goal:** the web tools are the actual contract, not a sketch of it.

- **B.1 Validator runs the real JSON Schemas.** Replace the heuristic
  `web/lib/validate.ts` with Ajv validating against the canonical schemas,
  vendored into `web/` at build time from `src/battinfo/data/schemas/**` with a
  drift check in web CI (same pattern the registry uses — third consumer, same
  discipline). Auto-detect record type by discriminator; render errors with
  authoring-vocabulary hints (reuse Phase 2's path→kwarg translations where
  cheap). Acceptance: the browser and `battinfo validate` agree on every
  `examples/**` record and on five deliberately broken ones.
- **B.2 Tool surface cleanup.** `validateCellType` → `validateRecord`; accept
  drag-and-drop of a JSON file; "load an example" buttons fed from the
  single-sourced `examples.generated.ts`.
- **B.3 JSON-LD gallery instead of a live converter.** Client-side JSON-LD
  generation would mean porting the semantic layer to TypeScript — permanent
  drift risk. Instead: a curated before/after gallery (record → rendered
  JSON-LD with the EMMO type stacking highlighted), generated at build from
  `examples/**` by the Python library itself. Honest, zero-drift, still shows
  the "real semantics" wow. (Decision 1 below if you want more.)
- **B.4 Convert page honesty pass.** Capability matrix (auto-detected formats
  vs `ws.convert('*.csv')` vs export-CSV-first), plus a downloadable sample
  cycler file and its BDF result so visitors can see the transformation without
  installing anything.
- **B.5 Property explorer.** A searchable table of every valid spec property —
  name, accepted units, EMMO IRI, example value — generated at build from
  `assets/mappings/domain-battery/**`. This is `battinfo properties show` for
  people who haven't installed anything, and the single strongest "real
  semantics" proof on the site.

## Phase C — Docs to Diátaxis completeness (Sphinx, 3–4 days)

- **C.1 THE tutorial: "Publish your first dataset."** One page (or notebook 06),
  mirroring A.2 exactly: sample cycler CSV (shipped fixture) → convert → search
  → add → save → validate → publish to Zenodo **sandbox** → submit to registry
  (mocked/staged). Every block executes in CI (extend the snippet harness /
  nbmake). The existing guides 01–05 become the "understand it deeply" track,
  linked at the end.
- **C.2 How-to gallery.** Short task pages, one job each, CI-executed where
  runnable: import from each supported source (surface the interop matrix —
  it's an adoption funnel, not an appendix), bulk-ingest 10k records
  (`bulk_save_session`), resume an interrupted submission, connect ORCID, tag a
  funding grant, fix the five classic validation errors.
- **C.3 Generated reference.** Phase 2's `Field(description=...)` work makes
  autodoc worth turning on: API reference from docstrings, CLI reference from
  the typer app, schema reference rendered from the JSON Schemas. Generated =
  cannot rot; hand-written API prose in `python-api.md` shrinks to the curated
  tour.
- **C.4 Explanation for the infrastructure audience.** One page telling the
  contract story: `schema_version`, `battinfo_version` stamping, deterministic
  IRIs and natural keys, registry gate + drift CI. This is the "can I build on
  this?" page for data engineers — the material exists in CHANGELOG/plan docs
  and needs assembling.
- **C.5 Versioned docs.** Publish docs per release tag with a version switcher
  (decision 2 below); "latest" tracks main with a banner.

## Phase D — Trust, citation, launch sweep (2 days)

- **D.1 Citation everywhere it matters.** Zenodo DOI minted for the 0.8 release
  (decision 3); `CITATION.cff` surfaced as a "Cite BattINFO" footer entry on
  web + a docs page; the Battery Genome paper referenced once it has a
  preprint DOI.
- **D.2 pyOpenSci/JOSS self-review.** Run the checklist, file the deltas
  (statement of need in README is the known gap); this doubles as prep if you
  ever submit to JOSS.
- **D.3 README badge row**: PyPI, CI, docs, DOI, license — and the test-count
  claim replaced by a live badge so it never goes stale again.
- **D.4 Launch hygiene**: link-checker CI over web + docs (Phase 1 fixed dead
  links once; a checker keeps them fixed), Lighthouse pass on the four key
  pages, dependabot backlog (18 alerts) cleared or triaged.

---

## Acceptance — the two human tests, made testable

1. **30-second test**: from the homepage, the value proposition is one visible
   sentence, and "Publish your data" is reachable in one click. (Reviewed by a
   person, but the *structure* is enforced: A.1/A.2/A.5 land together.)
2. **15-minute test**: the C.1 tutorial runs green in CI end-to-end from a
   shipped sample file, and a human has run it once for real (Zenodo sandbox
   DOI as the artifact).
3. **Tool honesty**: web Validate and `battinfo validate` agree on the full
   `examples/**` corpus (asserted in web CI against vendored schemas + drift
   check).
4. **No content drift**: every code snippet on web is either extracted from or
   asserted against library output; Sphinx snippets/notebooks stay under the
   existing execution CI.

## Decision points (up front, like last time)

1. **JSON-LD in the browser**: curated build-time gallery (recommended — zero
   drift, zero porting) vs a small serverless endpoint running the real Python
   converter vs a TS port (not recommended).
2. **Versioned docs hosting**: GitHub Pages with per-tag directories + switcher
   (recommended; stays in current pipeline) vs Read the Docs.
3. **Mint a Zenodo DOI for 0.8** to anchor D.1? (Recommended: yes, at release.)
4. **Hero recipe**: data-first `ws.quickstart()` journey (recommended) vs
   authoring-first `CellSpecification + publish()`. One of them leads; the
   other is a visible tab, not a competing hero.
5. **Sample data**: which real-ish cycler file ships as the tutorial fixture
   (a truncated Neware CSV is the obvious candidate — same policy as the
   bdf offline-fixtures work).

## Sizing and order

```
Phase 0  reconcile      (0.5 d)
Phase A  story/web      (2–3 d)   ← defines the narrative
Phase B  tools/web      (3–4 d)  ┐ parallel after A
Phase C  docs/Diátaxis  (3–4 d)  ┘ (different surfaces, no file overlap)
Phase D  trust/launch   (2 d)
```

Total ≈ 2 focused weeks. Natural PR boundaries: one per phase; B.1 (schema
vendoring into web) is its own PR since it adds a build step + CI job.
