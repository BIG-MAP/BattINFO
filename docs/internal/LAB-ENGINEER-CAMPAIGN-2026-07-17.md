# Lab-Engineer Readiness Campaign — review synthesis + phased plan

**Source: 2026-07-17 four-part review** — architectural materials/components
evaluation + two hands-on persona red-teams (A: materials→electrode→cell
build; B: protocol→equipment→test→convert→publish edge) + a documentation
red-team (12-task matrix, jargon/structure/honesty audits). Personas executed
every step for real in sandboxes; findings below are reproduced, not
hypothesized.

**One-line verdict:** the data model is research-grade and the records on
disk are complete and correctly cross-referenced — but the composition and
provenance a lab engineer authors are silently dropped by every ordinary
semantic output, the workspace surface doesn't cover materials/components at
all, several silent-data-loss traps exist, and the docs have no task-oriented
entry point for bench work.

## The defect clusters

**C1 — The emitter gap (BLOCKER).** `build_cell_spec_node` (the canonical
node used by publish/resolver/Zenodo/preview/export) drops: inline
electrode/electrolyte/separator/housing composition, all five `*_spec_id`
component references, and equipment/channel provenance on tests
(`hasTestEquipment` degrades to a nameless `schema:Thing`). Only the internal
`transform.json_to_jsonld.to_jsonld(target="domain-battery")` emits the
composition tree — and even it drops electrode→material (`material_spec_id`)
edges on constituent nodes. A user who inspects their published JSON-LD
concludes the feature doesn't work. (Persona A #9/#10, Persona B #18,
architecture eval §2.)

**C2 — Silent data-loss traps (HIGH).**
- `ws.convert()` auto-detect mapped a Digatron-style CSV via the wrong plugin
  and silently discarded `AhStep[Ah]`/`Step`/`Mode` — the capacity column of
  a capacity test — behind a success message. No unmapped-column report.
- `save_cell_spec` accepts dangling `*_spec_id` references without complaint
  (cell-fleet.md claims existence-checking; only `validate_record_report`
  catches it).
- `query_material_specs()` with no args searches the wheel's bundled examples
  and presents them as if they were the user's records.
- Cell instances mint DIFFERENT IRIs on the ws vs low-level surfaces for the
  same spec+serial (two parallel record stores) — identity landmine.
- Instance records auto-copy spec ratings into `measured={...}` with
  provenance `type='measurement'` — rated values masquerade as measurements.

**C3 — Broken/absent authoring paths.**
- `ws.template("test-spec")` output is rejected by `ws.load()` with 14
  pydantic errors (template emits scalars/min-max shapes the model refuses;
  null placeholders are themselves invalid). A voltage window is currently
  inexpressible in the `Quantity` model (schema has min/max; model doesn't).
- `ws.add`/`ws.template` hard-reject materials and all five component
  families (API-only, via imports the docs teach in deprecated form); those
  saves also skip JSON-LD/HTML artifact generation.
- No `started_at`/`ended_at`/`operator` inputs on `ws.add("test")` — the
  "when/who" of the lab-log triad has no input path.
- No `cas_number`/identifiers field on material-spec (first column of every
  lab inventory).
- `ws.validate()` doesn't exist (validation hides in save); `ws.list()`/
  `ws.export()` omit equipment/channels; ws.add("cell") is memory-only until
  ws.save() while ws.add("equipment") persists immediately, unannounced.

**C4 — Registry/platform gap.** `material_spec`/`material` and the component
families are not registrable ResourceTypes (no normalizers, zero live
records); the IRI layer below them is fully consolidated (`spec/` +
permanent aliases, live-verified) and ready.

**C5 — Documentation.** No cookbook/FAQ/troubleshooting anywhere; top-4
bench tasks grade B (recipes buried under architecture prose, split across
three APIs and two sites); tasks "print labels/QR" and "find what exists"
effectively absent; honesty gaps (CLI/workspace coverage overclaimed,
cell-from-components shown-as-working but labelled Phase-3 elsewhere, publish
key page named but nonexistent, DOI placeholder); jargon wall (EMMO never
expanded; URDNA2015 in marketing copy). Full task×doc matrix + ranked top-10
in the docs red-team report.

**Positives to preserve:** equipment registration UX (best of session);
teaching errors for unknown cell/channel and `did-you-mean` kwargs;
plain-English protocol steps → structured method[]; layered
validate_record_report; honest converter matrix + reading-a-record caveats;
draft-by-default Zenodo; fail-closed publish edge.

## Phased plan

**P0 — Emit what users author (pre-0.8; the release should not ship the
emitter gap).** Route the canonical cell-spec node (publish/resolver/
preview/export) through (or merge in) the domain-battery composition tree:
inline holders + `*_spec_id` refs emitted; electrode/electrolyte constituent
nodes carry `material_spec_id` edges (`@id`/`schema:isVariantOf`); test nodes
keep equipment/channel (`hasTestEquipment` becomes the real equipment node
with channel). Registry re-vendor + web regen follow. Acceptance: Persona A's
best_path.py assertion passes against `ws.preview_jsonld` and
`record_to_jsonld`, not just the internal transformer; Persona B's channel
provenance survives to the preview graph.

**P1 — Kill the silent traps (pre-0.8, small diffs).**
1. `ws.convert`/`convert_csv`: report unmapped source columns (warning w/
   column names + pointer to hints/bdf_columns); never green-light a lossy
   conversion silently.
2. Existence-check `*_spec_id` on save (default on, opt-out kwarg).
3. `query_*`: never fall back to bundled examples silently (require path or
   cwd + label provenance of hits); unify `source_root`/`directory`.
4. Deterministic instance IRIs across surfaces (single minting path).
5. Stop auto-copying spec ratings into instance `measured`.
6. Fix test-spec template↔load round-trip (emit {value,unit} shapes, prefill
   type enum, tolerate null placeholders) + add min/max to Quantity model
   (schema already has them).

**P2 — Docs cookbook (parallel with P0/P1; largely independent).** Implement
the docs red-team top-10: task cookbook landing ("I want to…", 12 tasks);
new how-tos: register-materials, build-a-cell-from-components,
find-existing-records, label-your-cells (segno/QR recipe + intake-GUI
pointer), name-only cells; honest capability table (workspace vs api vs CLI
× record types); publish/DOI/IRI truth pass; FAQ/troubleshooting page;
test-specs.md recipe-first reorder + glossary box; plain-language glossary
page linked from README tagline + every guide's first cell; switch doc
examples off deprecated imports; link register-equipment.md from guides.

**P3 — Workspace parity (post-0.8 acceptable).** `ws.add("material"|
"electrode-spec"|…)` + `ws.template(<family>-spec)` for the five families
(templates emit fully-populated per-family skeletons); artifact generation on
material/component saves; `ws.validate()` verb; `ws.list`/`ws.export`
completeness (equipment/channels/components); `started_at`/`ended_at`/
`operator` on ws.add("test"); `cas_number` (or identifiers map) on
material-spec; persistence consistency (persist-on-add everywhere or loud
"unsaved" notice); populate ValidationIssue.hint for the classic errors;
friendlier `*_spec_id` regex failures; accept electrode() holder objects as
component-spec bodies; make cell_description() mint ids.

**P4 — Registry + platform registrability (post-0.8).** Add
material_spec/material + electrode/separator/current-collector/electrolyte/
housing (spec+instance) to ResourceType, normalizers, schema gates, pipeline
IRI paths (equipment Phase-B playbook); re-vendor; live verify via the
resolver (aliases already work). Platform read pages for materials; the
"register materials" GUI slice becomes possible after this.

**Sequencing vs the 0.8 release:** P0+P1 are release-quality issues — ship
them BEFORE 0.8 (they change emitted artifact shape; better once than in
0.8.1). P2 lands whenever ready (docs deploy continuously). P3/P4 are the
first post-release arc, ahead of further GUI slices.

**Est. effort:** P0 ~2 days · P1 ~1-2 days · P2 ~2 days · P3 ~2-3 days ·
P4 ~2 days. P0/P1/P2 parallelizable across agents with independent
verification.

## Source reports

Full agent outputs (friction logs with verbatim tracebacks, task×doc matrix,
jargon/honesty audits, working best-path code) are preserved in the session
transcripts of 2026-07-17; Persona A's verified end-to-end script:
`scratchpad/persona-a/best_path.py` (sandbox). This file is the durable
synthesis.
