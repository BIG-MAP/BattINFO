# First-class materials: three-level model proposal — 2026-08-03

Status update (2026-08-26): Phase A shipped via #330 (kinds vocabulary,
deterministic ids, attribution, emission) and the kind reference anchors
became parameter claims (#347/#349). Still open from this document: the
Phase B genome-aggregation layer (per-kind property rollups, registry
/kinds endpoints, battery-genome.org kind pages, the OCP profile
convention) and the corpus migration/OCV regeneration status tracked on
the ocv-regen branch. The text below is the original proposal, kept as
the design record and the definition of that remaining Phase B work.

Status: DRAFT for decision. Trigger: the OCV dataset readiness test
(battinfo-records#6, READINESS-REPORT.md) showed materials are a
half-finished integration (random ids H1, no stamping/attribution H2, no
JSON-LD M6, no blessed API). The user has ruled this foundational and
release-gating. This proposal defines the target model and the path.

## The three levels

The user's framing, adopted verbatim as the architecture:

1. **Generic material** — graphite, NMC811, LFP: the *kind*.
2. **Manufactured material spec** — a manufacturer's (or lab's) specific
   product with datasheet properties: the *product*.
3. **Material instance** — the actual batch/lot that is in a cell: the
   *portion*.

This is the existing spec+instance philosophy with one level above it, and
it mirrors how cells already work (chemistry/format vocabulary above
cell_spec above cell).

## Level 1: MaterialKind — a curated vocabulary, NOT records

The single most consequential decision in this proposal. Generic graphite
is universal reference data: the genome's cross-dataset promise ("all
graphite half-cell OCVs") requires every publisher to converge on ONE
identifier for graphite. If level 1 were user-authored records, the corpus
grows fifty graphites. So kinds are a shipped, versioned, curated
vocabulary — like the property vocabulary, governed by PR — not a record
type.

Each entry:
- `key`: canonical snake_case (`graphite`, `nmc811`, `lnmo`, `lfp`,
  `silicon`, `silicon_graphite`, `nmc111`, `nmc532`, `lithium_metal`, ...)
- `label`, `family` (active_anode | active_cathode | binder |
  conductive_additive | electrolyte_solvent | electrolyte_salt |
  separator_material | current_collector_material | other)
- `formula` template / stoichiometry where meaningful
- `emmo` IRI where a class exists (the emitter's existing chemistry->EMMO
  map seeds this); labeled `ns#` fallback where not (the established
  pending-term pattern; upstream additions go on the
  ontology-additions-needed backlog)
- `aliases` for tolerant import ("NMC 811", "LiNi0.8Mn0.1Co0.1O2",
  "Si/Gr") — directly serves the interop adoption funnel

Serving: kinds are emitted into the generated records vocabulary
(battinfo-records.ttl + context, the #318 pipeline) so each kind has a
dereferenceable IRI with EMMO seeAlso/equivalence. The registry vocab
endpoint (intake already consumes one) serves the list to UIs.

Fixes en passant: the engineer-review "chemistry: NMC flagged as
unmapped" class of warnings — aliases + kinds make common shorthand
resolve.

## Level 2: MaterialSpec — first-class records

The manufactured (or lab-synthesized) product. Promotion to full
citizenship equal to cell_spec:

- **Identity (fixes H1)**: deterministic content-derived id, minted like
  the other five engine types. Basis: normalized
  (manufacturer_org, product_name, grade/version). Lab-synthesized
  materials use the same triple with the lab as manufacturer and the
  recipe/batch-family name as product (e.g. SINTEF / "aqueous-processed
  silicon" / "v2"). Re-authoring the same product is a no-op, never a
  duplicate.
- **Required `kind`**: every spec names its level-1 kind (controlled).
  This is the query backbone.
- **Manufacturer as org link**: `manufacturer.id` -> organization record
  IRI (link-integrity gate applies), name fallback tolerated with the
  usual warning.
- **Properties**: datasheet values via the property mechanism (D50, BET
  surface area, tap density, theoretical/rated specific capacity,
  moisture, coating e.g. carbon on LFP, morphology), each eligible for
  the flagship's per-property datasheet provenance (raw text, page,
  confidence).
- **Attribution (fixes H2)**: contributor / license / funding allowed on
  the schema and stamped by ws.save exactly like every other record.
- **API**: `ws.add("material_spec", ...)` blessed; `ws.load` drafts;
  template support. No `ws._ws` required.
- **Emission (fixes M6)**: `record_to_jsonld` support; kind -> EMMO class
  node; gold-standard panel coverage.

## Level 3: Material — instance records

An actual batch/lot/portion:

- `spec` link (level 2, required), `lot`/batch number, received/opened
  dates, supplier order reference, storage conditions, amount.
- **As-received / as-characterized measurements**: an OPEN property block
  (the closed-vocabulary mistake on cell-instance `measured` is not
  repeated here; unmapped keys get the standard labeled-fallback +
  warning treatment).
- Identity: deterministic from (spec_id, lot). `ws.add("material",
  spec=..., lot=...)`.

## Linkage into cells: progressive fidelity

Electrode composition components (and electrolyte solvents/salts,
separator materials) accept any of three reference levels:

- a **kind key** (minimum: "the anode is graphite") — resolves to the
  vocabulary IRI/EMMO class;
- a **material_spec IRI** (better: "Targray NMC811 grade X");
- a **material instance IRI** (best: "this lot") — typically on the cell
  *instance*/build rather than the spec.

Emission renders whichever level is present as a properly-typed linked
node; the link-integrity gate validates internal IRIs; tolerant import
maps free-text names through the alias table with warnings. This ladder is
the adoption funnel applied to materials: express at the level you know,
upgrade without re-modeling.

## What this fixes from the readiness report

H1 (deterministic ids + dedupe), H2 (stamping + attribution), M6
(JSON-LD), the ws._ws-required-for-materials gap, the NMC-shorthand
warning class, and (level 3) the closed-measured-vocab lesson. M2 (the
str|list[str] character-explosion) is an independent bug fixed in the same
wave. NOT in scope here: half-cell configuration vocabulary,
Test.conditions model field, instance as-built slots on cells — those ride
in the same release wave as small items but are separate from the
materials architecture (listed in the wave plan).

## Migration

- Existing corpus: 17 material-spec + 2 material records carry random
  ids. Re-mint deterministically; supersede the old ids per
  IDENTIFIER_POLICY (superseded segments resolve forever). Registry
  backfill re-keys references (same machinery as the manufacturer
  backfill).
- battinfo-records#6 (OCV branch): hold Phase-3 publishing until this
  lands; the authoring script is deterministic — regenerate the 7
  material specs (and the 9 cell specs' links) under the new model, then
  publish once, clean. No double-publish.
- Schemas: additive fields (kind, attribution, lot, ...) keep
  schema_version 0.2.0; generated through the single-source pipeline;
  registry re-vendor after merge.

## Delivery plan (release-gating: Phase A blocks the 0.8 tag)

**Phase A — the model (one parallel wave, ~4 agents):**
- A1 kinds: vocabulary file + seed (~40 entries: the 7 OCV materials,
  common actives incl. lithium_metal, binders PVDF/CMC/SBR, carbon black,
  LiPF6/LiFSI, EC/EMC/DMC/FEC/VC, separator polymers, Al/Cu) + alias
  table + vocab-pipeline emission + governance note.
- A2 engine: deterministic ids for both material types (H1), dedupe,
  ws.save stamping, attribution schema fields, migration/re-mint script.
- A3 surface: ws.add for both types, record_to_jsonld, gold-standard
  panel, docs page ("Materials: kind, spec, instance").
- A4 rides-along: M2 string-explosion fix; Test.conditions model field;
  the model-accepts/schema-rejects M1 pair.

**Phase B — fast-follow (not tag-gating):** composition linkage ladder in
electrode/electrolyte models + emission, registry/platform material pages
+ kind facets, corpus migration execution + OCV regeneration + publish,
EMMO term upstreaming, half-cell configuration vocabulary.

**Then:** 0.8 release train (batterydf pin unchanged), regenerated OCV
publish via records-bot, Zenodo version update, definitive blind
re-review.

## Refinements (user direction, 2026-08-03)

1. **Kinds anchor to the chemical-substance domain ontology.** Level-1
   entries do not invent semantics: each kind's canonical semantic
   identity is its chemical-substance class IRI (domain-chemical-substance
   in the EMMO ecosystem); the battinfo `key` is the ergonomic handle.
   Kinds missing from the ontology go on the ontology-additions backlog
   and carry the labeled ns# fallback until upstreamed. Kind entries MAY
   carry curated reference values with citations (e.g. graphite crystal
   density 2.26 g/cm3, theoretical capacity 372 mAh/g) — these are the
   "generic" anchors the genome compares against.
2. **Processing lives at the instance level.** Aqueous vs NMP (and any
   processing-into-coating descriptor) is NOT spec identity — it belongs
   on the material instance / electrode build (processing route, solvent,
   coating context). Spec identity stays (manufacturer, product, grade).
   For the OCV dataset this means the electrode-source distinctions keep
   their spec grouping while AQ/NMP moves to instance processing blocks.
3. **The genome aggregation: per-kind property distributions.** The kind
   is the aggregation axis of the Battery Genome. Because every spec
   carries a required kind and every instance links a spec, the registry
   can roll up, per (kind, canonical property): the curated reference
   value, the distribution of spec-declared (datasheet) values, and the
   distribution of instance-measured values. Mechanism:
   - Registry: materialized per-kind rollup updated at publish/promotion
     (n, mean, std, quantiles, histogram bins per property and level),
     served at e.g. `/kinds/{key}` and
     `/kinds/{key}/properties/{prop}/distribution`. Conformance-flagged
     sources are excluded or marked; every datum carries its record IRI
     for click-through.
   - Platform: battery-genome.org kind pages (`/materials/graphite`):
     header (label, formula, chemical-substance link, reference values +
     citations), then per-property distribution visualisations —
     reference value as a marker, spec-reported vs instance-measured as
     overlaid distributions with counts, each point resolving to its
     record.
   - Curves (OCP profiles): OCP is a function, not a scalar. Convention:
     a small derived profile artifact (downsampled V vs normalized
     capacity/SOC, few hundred points) attached at publish time alongside
     the full dataset distribution; the kind page overlays profiles per
     kind (measured from tests on half-cells whose working-electrode kind
     matches; declared from datasheets where they exist). The Flores OCV
     dataset becomes the founding population for 7 kind pages, and the
     profiles feed the cell-design tool's OCP needs directly.
   - Comparability: rollups aggregate only canonically-keyed,
     unit-normalized properties (the property vocabulary + save gate
     guarantee); basis-dependent properties aggregate within their
     canonical key only.

Phase impact: Phase A unchanged in scope except A1 sources kinds from
chemical-substance and admits curated reference values, and A2/A3 place
processing on instances. The rollup + kind pages + profile convention
join Phase B (registry + platform work, not tag-gating). Corpus migration
+ OCV regeneration remain Phase B; the OCV publish then seeds the first
kind pages with real distributions.

## Decisions requested

1. Level 1 as curated vocabulary (not records) — the load-bearing choice.
2. Spec identity basis (manufacturer, product, grade) incl. the
   lab-synthesized convention — acceptable?
3. Kind seed scope: actives-only first, or the full ~40 incl. inactive
   components (recommended: full — electrolytes and binders are where
   free-text chaos lives)?
4. Timeline: Phase A gates the tag (accepted release slip past Tuesday);
   batterydf publishes independently at the steering meeting.
