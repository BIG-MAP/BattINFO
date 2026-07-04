# BattINFO Robustness Triage — June-27 review re-verified vs current main (0a3f8d3), 2026-07-01

Re-verification of every finding in `ROBUSTNESS_REVIEW_2026-06-27.md` against current `main`
(47-agent workflow: classify each finding fixed/partial/open, then adversarially re-verify every
"fixed" claim by trying to reproduce the original defect). A Fable-5 cross-check (second-model
diversity lens) was attempted but Fable 5 is currently unavailable (gated access).

## Headline
**16 of 32 still open/partial · 14 confirmed-fixed · 1 not-a-bug · 1 un-triaged (A-6, agent errored).**
**0 flipped** — no finding classified fixed was reproduced as still-broken (the Phase 3/4/5 hardening holds).

## Confirmed FIXED (trust these — closed by the Phase 3/4/5 hardening)
C-1, C-2, C-3 (commit d7050ff); C-6 (0a3f8d3); C-7, R-3, R-4, A-1 (9bd47d5); R-1, R-2, R-5;
R-9, A-2 (41b49a2); D-5. — **A-7 = not-a-bug** (env>file>default precedence is correct; doc/coverage gap only).

## UN-TRIAGED
- **A-6** (credentials file world-readable; registry error body unbounded/unscrubbed) — the classify
  agent hit the StructuredOutput retry cap and did not return. Needs a manual pass; treat as likely-open
  (security hygiene) until checked.

## STILL-OPEN PUNCH-LIST (by severity, then effort)

### CRITICAL
- **C-4** — skip-if-exists plot writers reuse a stale/garbage `<stem>.png`/`.plot.json` as "success";
  `ws.process()` then computes a real SHA-256 over the garbage and publishes it (valid checksum, invalid
  content). Fix: validate before reuse (json.loads + Plotly keys; PNG magic + nonzero size), else regenerate;
  atomic `.tmp`+os.replace; `ws.process()` must not skip on name alone and must refuse a content-insane
  distribution. `processing.py:249-251,310-312`; `ws.py:3225-3226,3244-3256`. Pairs with C-5, R-8.

### HIGH
- **R-6** — subset `ws.submit()` silently drops a cross-session relationship when a NON-selected sibling on
  disk is corrupt; record still published ok=True, no warning; the corrupt sibling never reaches the C-6
  fail-closed gate (which only covers the selection). Fix: stop `except Exception: continue` in `_load_all`
  (`ws.py:2852-2865`), `_read_record_sets` (`744-747`), `_bundle_data_files` (`3870-3921`); collect+surface,
  raise SubmitError unless allow_partial. **Same root cause as R-10's open half — one fix closes both.**
- **R-7** — `ws.zenodo(publish=True)` mints a DOI on an incomplete deposit (a missing file-scheme
  distribution is dropped silently; no validation before publish). Fix: `validate_publication_report(...,
  policy=publisher)` before `publish_deposit` and raise; warn instead of silently dropping. `ws.py:3890-3898,
  3442-3641`. Pairs with A-5, D-4.
- **R-10 (partial)** — submit integrity pass now fails closed on BOM/latin-1 (fixed half), but `_load_all`
  still silently strips relationships on a subset submit when a sibling is BOM/latin-1. **DEDUP: open half == R-6.**
  Also: unify encoding policy once via `_jsonio.read_json` across the ~35 bare `read_text(encoding="utf-8")` sites.

### MEDIUM
- **C-5** — degenerate CSV (0-row/1-row/all-NaN) yields a "successful" blank/garbage plot preview that
  `ws.process()` publishes; only a truly 0-byte file returns (None,None). Fix with C-4 (same two writers).
- **A-3** — on any 409, `_do_submit` blindly bumps source_version (-v2/-v3) with no content comparison; fresh
  `generated_at` makes every re-run byte-different → duplicate proliferation. Fix: distinguish duplicate-identical
  vs version-conflict-changed (409 body / content-hash); strip volatile timestamps from identity. `ws.py:6321-6329`.
  Pairs with A-4. (NB: the registry side of this is already fixed by Cap-1 volatile-strip dedup — this is the
  BattINFO-client half.)
- **A-4** — `AuthoringWorkspace.save()` hardcodes mode="upsert", silently overwriting a same-IRI-different-content
  file; the create_only guard is unreachable. Fix: expose `mode`, thread through; raise on mismatched-identity
  upsert unless allow_overwrite. `ws.py:1959,1968`; `api.py:2898-2911`.
- **A-5** — transient timeout/5xx on the irreversible `publish_deposit` is not retried and triggers no
  GET-to-confirm; user can't tell if publish committed; a mid-flow failure can orphan a draft. Fix: bounded
  GET retry; on publish timeout, GET the deposit and treat state=='done' as success. `zenodo.py:67-90,125-127,592`.
- **D-1** — four unit-bearing SpecSet props (ac_internal_resistance, initial_coulombic_efficiency,
  self_discharge_rate, state_of_health) have no SPEC_UNIT_COMPATIBILITY entry, so `state_of_health={value:95,
  unit:'furlongs'}` passes strict/publisher. Fix: add the four entries + bounds + a coverage-guard test.
  `validate/semantic.py:20-90,424`. **Cheap, high-leverage.**
- **D-3** — no validator rejects non-absolute/`file://`/bare-string `@id`-typed objects → cwd-leaking
  `file:///...` IRIs in exported RDF. Fix: `@id` absolute-http sweep in `validate/jsonld.py`; tighten
  `_is_absolute_uri` (`publication.py:179-183`). Pairs with D-2.
- **D-7** — `_group_files_by_cell` silently collapses distinctly-named cells into one synthetic cell. Fix:
  `contribution.py:991-992` raise ValueError when len(raw)>1 unless n_cells==1 explicit. **Cheap.**

### LOW
- **D-2** — unmapped unit emitted as bare string under `hasMeasurementUnit` (@id-typed) → `file://` IRI on
  rdflib export. Fix: emit `schema:unitText` literal when unmapped (`jsonld.py:215-225`). Pairs with D-3.
- **R-8** — `convert_raw_to_bdf` reads a corrupt cached `.bdf.parquet` with no integrity check, swallows,
  returns no-deps sentinel, leaves the corrupt file → permanent poisoning. Fix: guard read, delete+regenerate
  or raise; atomic write; distinct sentinel. `processing.py:218-228`. Pairs with C-4.
- **D-6 (partial)** — solvent phantom-dup FIXED; `import_converter_jsonld_record` still runs no schema
  validation of its output. Fix: add `validate=` running `_validate_canonical_record`. (Low: C-6 re-validates at submit.)
- **D-4** — `preview_jsonld()` writes the file before validating and returns the path unconditionally. Fix:
  validate before write. `ws.py:3835,3843-3859`. (Not a submission defect; the real publish gate is R-7.)
- **D-8** — `WorkspaceStateStore.open()` has no schema_version compat check. Fix: read+compare major version
  before model_validate; raise a clear version error. `workspace_state.py:461-464`.

## Suggested implementation order (cheapest-highest-leverage first)
The findings that can currently make BattINFO **silently produce or submit bad data** (the mission invariant):
**C-4, R-6, R-7, R-10-open, D-1, D-3, D-7** — prioritise these over pure fidelity/UX (D-2, D-4, D-8, A-3, A-4, A-5, R-8, D-6).

1. **Tier 1 — cheap real code:** D-1 (4 unit entries + test), D-7 (return→raise), D-2 (unitText, with D-3), D-4 (validate-before-write), D-8 (version gate).
2. **Tier 2 — shared root cause:** **R-6 + R-10-open together** (harden the three swallow-sites + unify encoding in `_jsonio.read_json`) — one change, two HIGHs. Then **C-4 + C-5 + R-8** (validate-before-reuse + atomic-write in `processing.py`; C-4 is CRITICAL). Then D-3 (@id sweep, with D-2).
3. **Tier 3 — Zenodo publish path cluster:** R-7 + A-5 + D-4-substance (validate before publish; confirm-state-on-timeout; warn on dropped dists) — one focused PR.
4. **Tier 4 — authoring identity:** A-4 then A-3.  **Also: manually triage A-6.**
