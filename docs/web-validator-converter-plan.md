# Web Validator & Converter Tool — Plan

Status: proposal · Owner: BattINFO web · Last updated: 2026-06-17

This plan defines two first-class, browser-based tools for `battinfo.org`:

1. **Validate** — paste or upload a record and get the same structured issues the
   Python package and registry produce.
2. **Convert** — turn human-authored BattINFO JSON into canonical EMMO
   `domain-battery` JSON-LD (and back), with a live, inspectable transform.

The design goal is a credibility bar set by the field's best reference tools:
the [Schema.org validator](https://validator.schema.org), the
[JSON-LD Playground](https://json-ld.org/playground/), the
[SHACL Playground](https://shacl.org/playground/), and the
[QUDT / OBO](https://obofoundry.org) registries. Those tools win trust by being
**instant, transparent, shareable, and authoritative** — the same engine the
backend uses, never a divergent re-implementation.

---

## 1. Why these two tools

BattINFO already has a contract-grade validator and a deterministic transform in
the Python package (see [validation-contract.md](validation-contract.md),
[validation-roadmap.md](validation-roadmap.md), and
[converter-compatibility.md](converter-compatibility.md)). What is missing is a
**zero-install front door**: a way for a researcher to paste a datasheet-derived
JSON and immediately see (a) whether it is valid and (b) what Linked Data it
becomes — without a Python environment, an account, or reading the spec first.

That front door is how schema.org, JSON-LD, and the Gene Ontology convert curious
visitors into adopters. It is the single highest-leverage addition to the site.

### Non-goals

- The web tools are **not** the source of truth. The Python package + registry
  remain canonical. The web layer must produce byte-identical results or clearly
  label itself as a structural pre-check.
- No data is persisted server-side without explicit user action (share links are
  opt-in and content-addressed).
- The converter does not replace BattINFO Converter's Excel workflow; it exposes
  the canonical `battinfo.transform` engine that BattINFO Converter is migrating
  onto.

---

## 2. The "same engine" principle (critical)

The biggest failure mode is **drift**: a JS re-implementation that disagrees with
the Python validator, so a record "passes on the website" and fails on `battinfo
validate`. Every credible standard avoids this by running the real engine.

We have three options, in increasing fidelity:

| Tier | Mechanism | Fidelity | Cost |
|------|-----------|----------|------|
| **T0** | Hand-written TS structural checks (today's `lib/validate.ts`) | low — shape only | none |
| **T1** | Real validator behind a tiny HTTP API (FastAPI) the site calls | full | a service to host |
| **T2** | `battinfo` compiled to WASM via Pyodide, run in-browser | full, offline | bundle size / cold start |

**Decision:** ship **T1 as the authoritative path** and keep **T0 as the instant,
offline pre-check** that runs on every keystroke. T0 gives sub-millisecond
feedback and works with JS disabled fallbacks; T1 gives the canonical verdict on
demand. T2 (Pyodide) is a later enhancement for true offline parity, evaluated
once the validator's pure-Python core has no native-only deps.

The UI must always make clear **which engine produced a result** (a labelled
badge: `structural pre-check` vs `canonical · battinfo X.Y.Z`).

---

## 3. Architecture

```
┌─────────────────────────── battinfo.org (Next.js) ───────────────────────────┐
│                                                                               │
│  /validate                         /convert                                   │
│   ├─ editor (Monaco/CodeMirror)     ├─ editor (authored JSON)                  │
│   ├─ T0 structural check (instant)  ├─ output tabs:                            │
│   │   → lib/validate.ts             │    authored · domain-battery JSON-LD ·   │
│   ├─ "Validate canonically" ───┐    │    converter-compatible · N-Quads · RDF  │
│   └─ results: issue list,      │    ├─ T0 illustrative transform (instant)     │
│       grouped by layer,        │    └─ "Convert canonically" ────┐             │
│       severity, code           │                                  │             │
│                                │                                  │             │
└────────────────────────────────┼──────────────────────────────────┼───────────┘
                                  │  POST /v1/validate                │ POST /v1/convert
                                  ▼                                  ▼
                  ┌──────────────────────────────────────────────────────────┐
                  │  battinfo-tools API  (FastAPI, stateless, CORS-scoped)     │
                  │   /v1/validate   → battinfo.validate.validate_json(...)    │
                  │   /v1/convert    → battinfo.transform.to_jsonld(...)       │
                  │   /v1/import     → battinfo.import_converter_jsonld(...)   │
                  │   /v1/schemas    → served JSON Schemas + context docs      │
                  │   /v1/version    → {battinfo, domain_battery, electrochem} │
                  │  pinned to a published battinfo release; no DB; rate-limited│
                  └──────────────────────────────────────────────────────────┘
```

Key points:

- The API is a **thin wrapper** over existing public functions. No new validation
  or transform logic lives in the service — it imports `battinfo`.
- Stateless and side-effect free per request → trivially horizontally scalable,
  deployable next to the existing registry on Render.
- The API echoes the exact `battinfo` and EMMO `domain-battery` /
  `domain-electrochemistry` versions in every response so results are
  reproducible and pinnable (mirrors how the package pins EMMO).

---

## 4. API contract

Reuse the **existing** structured issue model from
[validation-contract.md](validation-contract.md) verbatim — do not invent a new
one. The web tool renders that payload directly.

### `POST /v1/validate`

Request:
```json
{
  "record": { "...": "the authored JSON or JSON-LD" },
  "policy": "default",            // default | strict | publisher | ingest
  "resource_type": "cell-type",   // optional hint; otherwise inferred
  "source_root": null              // optional, for cross-reference checks
}
```

Response (the canonical JSON-mode payload already emitted by `battinfo validate
--format json`):
```json
{
  "ok": true,
  "mode": "json",
  "policy": "default",
  "profile": "cell-type",
  "engine": { "battinfo": "0.X.Y", "domain_battery": "0.18.7", "domain_electrochemistry": "0.33.0" },
  "issue_count": 1,
  "error_count": 0,
  "warning_count": 1,
  "errors": [],
  "issues": [
    {
      "code": "semantic.short_id_mismatch",
      "severity": "warning",
      "path": "cell_type.id",
      "message": "...",
      "hint": "...",
      "validator": "semantic",
      "resource_type": "cell-type",
      "profile": null
    }
  ]
}
```

### `POST /v1/convert`

```json
{
  "record": { "...": "authored JSON" },
  "target": "domain-battery"      // domain-battery | converter-compatible
}
```
Response: `{ "jsonld": { ... }, "engine": { ... }, "warnings": [ ... ] }`.
Lossy mappings surface as `warnings` (mirrors the converter adapter's
"records lossy areas as warnings, never silently drops" rule).

### Convert targets

`target` selects the export format. Beyond the JSON-LD views, the package
exposes a **BPX** target for physics-modelling workflows:

| `target` | Output | Engine |
|----------|--------|--------|
| `domain-battery` | Canonical EMMO JSON-LD | `battinfo.transform.to_jsonld` |
| `converter-compatible` | Legacy BattINFO-Converter JSON-LD | `battinfo.transform.to_jsonld` |
| `bpx` | A BPX `"Partial"` document (Header + `Parameterisation.Cell`) | `battinfo.to_bpx` |

The **BPX** target turns a cell specification (and optional instance) into a
[BPX](https://github.com/FaradayInstitution/BPX) parameter file, populated with
everything a spec can supply — nominal capacity, voltage cut-offs, and, when cell
dimensions are present, cell volume, external surface area, and density. BPX also
needs electrode/electrolyte/separator **physics** parameters (thickness,
porosity, transport, OCP, particle data) that a specification does not contain, so
the export is a `"Partial"` model and the response lists `missing_required` so the
caller knows exactly what a downstream parameterisation step must still provide.
This is the "as much information as is available" contract — fill what is known,
report what is not, invent nothing.

```python
from battinfo import to_bpx

result = to_bpx(cell_spec_record, cell_instance=instance_record)
result.save("cell.bpx.json")     # valid Partial BPX
result.missing_required          # ['Electrode area [m2]', ...]
```

### `POST /v1/import`

Accepts BattINFO-Converter-flavoured JSON-LD and returns the linked BattINFO
object package (`import_converter_package`). This is the "bring your old
converter output in" on-ramp.

### Errors

Transport errors (bad JSON, oversized payload, rate limit) return RFC 9457
`application/problem+json`. Validation *failures* are **200 OK** with `ok:false`
— a failed record is a successful validation, not an API error.

---

## 5. UX design

### 5.1 Validate page

Inspired by the schema.org validator (left input / right structured results) and
the GO/OBO habit of making the authoritative download and version obvious.

- **Input modes** (tabs): `Paste JSON` · `Upload file` · `From URL` · `Sample ▾`.
  Samples dropdown pulls the real `examples/**` records (one per record type).
- **Editor**: CodeMirror 6 with JSON syntax highlighting, line numbers, and
  inline error squiggles from T0. Lightweight; no Monaco bulk.
- **Engine + policy controls**: a policy selector (`default / strict / publisher
  / ingest`) and a clearly-labelled engine badge.
- **Results panel**, grouped the way the issue model already separates concerns:
  - a top **verdict card** (pass / fail, error & warning counts, engine + policy
    + profile echoed back);
  - issues grouped by **layer** — `schema` · `reference` · `semantic` ·
    `publication` — each issue showing `code` (monospace, copyable), `path`
    (click to focus that line in the editor), `message`, and `hint`;
  - severity chips (`error` red, `warning` amber) consistent with the package.
- **Deep-linkable**: `?policy=strict` and a "Copy share link" that encodes the
  record (gzip+base64 in the URL fragment, client-side, nothing stored) — the
  JSON-LD Playground's `startTab`/permalink pattern.
- **"Run in your terminal"** affordance: a copy-paste `battinfo validate` command
  reproducing exactly what the page did, so the web tool is a gateway to the CLI,
  not a dead end.

### 5.2 Convert page (the playground)

Modelled on the JSON-LD Playground's multi-tab output, adapted to BattINFO's
two-views-over-one-model design (see converter-compatibility.md §Round-Trip).

- **Left**: authored JSON editor (with the same sample selector).
- **Right**: output **tabs**:
  - `domain-battery` — canonical EMMO JSON-LD (the default, hero output);
  - `converter-compatible` — legacy BattINFO-Converter shape, for migration;
  - `N-Quads` — the normalised RDF (URDNA2015) so RDF people trust it;
  - `Expanded` / `Compacted` — standard JSON-LD algorithm views;
  - `Diagram` — a small node-link view of the `@type` stack + `hasProperty`
    quantity pattern, so non-RDF users *see* what the semantics buy them.
- **Inline annotations**: hovering a value in the output highlights the authored
  field it came from, and shows the EMMO IRI it mapped to (pulled from the
  curated `assets/mappings/` tables). This is the "show, don't tell" moment that
  makes the ontology tangible — the single most persuasive screen on the site.
- **Lossy-mapping banner**: any field that could not be mapped is listed, never
  hidden — matching the converter adapter's contract.
- **Round-trip check**: a "↔ verify round-trip" button that imports the emitted
  JSON-LD back and diffs it, demonstrating the lossless guarantee.

### 5.3 Shared

- Both tools share the editor component, sample loader, engine-badge, and
  share-link logic (`web/lib/tools/`).
- Fully keyboard-accessible; results are real DOM (screen-reader friendly), not
  canvas.
- Empty/default state shows a real worked example already loaded, so the tool is
  never a blank box (schema.org and the JSON-LD Playground both do this).

---

## 6. Data & content sourcing

- **Samples** come from a build-time sync of `examples/**` (replacing the inlined
  placeholders in `web/lib/examples.ts`). One canonical record per type:
  cell-type, cell-instance, test, dataset, test-protocol, organization.
- **Schemas + context** are served from the package's `assets/` so the validator
  and the published JSON Schemas can never disagree.
- **Mapping hovers** read the curated `assets/mappings/domain-battery/` tables.
- A CI check fails the build if a synced sample no longer validates under the
  pinned engine — the website can never ship a broken example.

---

## 7. Delivery phases

| Phase | Scope | Outcome |
|-------|-------|---------|
| **P0 (done)** | T0 structural validator, static Examples page | instant shape feedback |
| **P1** | `/convert` page with T0 illustrative transform + output tabs + sample sync | the persuasive "JSON → JSON-LD" demo, no backend |
| **P2** | `battinfo-tools` FastAPI (`/v1/validate`, `/v1/convert`, `/v1/version`); wire "Validate/Convert canonically" buttons; engine badges | canonical, same-engine results online |
| **P3** | CodeMirror editor, policy selector, layer-grouped results, path→line focus, share links | a tool that feels first-class |
| **P4** | `/v1/import` converter on-ramp, round-trip verify, mapping-hover diagram | full converter story; migration surface for BattINFO Converter |
| **P5 (stretch)** | Pyodide/WASM in-browser canonical engine for offline parity | no-backend authoritative validation |

P1 is shippable immediately and is the highest-value visible upgrade. P2 makes it
authoritative. Everything after is polish that compounds trust.

---

## 8. Open questions

- **Hosting**: co-locate `battinfo-tools` with the registry on Render, or a
  separate lightweight service? (Leaning separate + pinned, so the public tool
  can't be destabilised by registry changes.)
- **Rate limiting / abuse**: anonymous POST of arbitrary JSON needs a payload cap
  (e.g. 256 KB) and per-IP limits. No auth for read-only validation/convert.
- **Versioned engine pinning**: expose a version switcher (validate against
  `battinfo 0.X` vs `0.Y`) the way the JSON-LD Playground exposes processor
  modes? Useful once there is more than one published release.
- **Pyodide feasibility**: does the validator core import cleanly under Pyodide
  (no native-only deps)? Determines whether P5 is realistic.
