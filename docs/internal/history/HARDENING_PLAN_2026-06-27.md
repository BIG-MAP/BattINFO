# BattINFO Hardening & `submit()` Implementation Plan

> Generated 2026-06-27. Companion to [ROBUSTNESS_REVIEW_2026-06-27.md](./ROBUSTNESS_REVIEW_2026-06-27.md).
> **Architectural decision (locked):** the registry is a **curated index**, not a database of record. The **archive (Zenodo deposit carrying the canonical BattINFO record) is the source of truth.** `ws.submit()` writes to **staging by default**; records reach the public genome only by passing a **promotion gate**. The registry is a **derived, rebuildable index** over archived records.

---

## 0. What the curated-index decision changes about the backlog

The decision *re-weights* the review. It moves urgency **toward canonical-record correctness** (the archived artifact is now authoritative and permanent, minted with a DOI) and **moderates** the submit-egress-visibility findings (a bad submit lands in staging, not live — but it must still fail closed and be observable).

| Finding class | Review severity | New priority | Why the decision moves it |
|---|---|---|---|
| Canonical-record correctness — C-1/C-2 IRI collision+overwrite, C-3 NaN, importer fidelity (D-5/D-6/IO-*) | crit/high | **UP — top of list** | The record that gets archived with a DOI is now the source of truth. A wrong record is permanent and citable. Correctness must be airtight *before* a record can be promoted/archived. |
| Durable-write integrity — R-5 atomic write, `_write_workspace` rmtree-first | high | **Stays high** | The local authoring + curated store is the staging area for the source-of-truth artifact. Corruption here poisons what gets archived. |
| Dedup / idempotency — A-3 409 version-bump, C-1 overwrite | medium-high | **UP** | An *index* must not duplicate or silently overwrite. This is now a core invariant, not an edge case. |
| Submit egress visibility — R-1/R-2/R-3/R-4 | crit/high | **Still fix, urgency moderated** | Staging is a backstop, so a silent drop no longer corrupts live data — but you still must know whether your submission to staging succeeded. Fail-closed + observable, just no longer "data-loss-critical." |
| Registry defense — A-1 retry/classification | high | **Moderated** | No live public data at stake on a transient error; still worth retrying a cold-start so staging submission doesn't spuriously fail. |
| Semantic fidelity — EMMO IRIs unused, D-2/D-3 RDF round-trip | low-med | **UP** | The archived JSON-LD is now the authoritative semantic artifact; it should carry EMMO IRIs and be round-trip-clean. |

**Net:** the plan leads with correctness + integrity of the canonical record (Phases 1–3), then builds the promotion gate and archive-anchoring that the curated-index model requires (Phases 4–5), with tests/CI threaded throughout (Phase 6).

---

## Phase 1 — Flip the front door: `submit()` is staged-by-default

**Goal:** self-submissions land in the registry's staging queue (`status=validated`, awaiting promotion), not the public surface. This is a small change over machinery that already exists end-to-end (`pending()`/`approve()` already consume staged submissions).

- **1.1 Thread `publication_mode` through the authoring submit path.** Add a `publication_mode: str = "staged-publication"` parameter to `AuthoringWorkspace.submit()` ([ws.py:2596](BattINFO/src/battinfo/ws.py#L2596)) and pass it into the payload builders, replacing the hardcoded `"publication_intent": {"mode": "canonical-publication"}` at [ws.py:5937](BattINFO/src/battinfo/ws.py#L5937) and its `_test_*` / `_dataset_*` siblings. The low-level client `submit_publication_package` ([api.py:1385](BattINFO/src/battinfo/api.py#L1385)) already supports the param — this just wires it up.
  - *Decision to confirm:* the exact staged-mode token the registry accepts (`"staged-publication"` is the presumed mirror of `"canonical-publication"` — confirm against the registry submission schema; this is a shared contract).
- **1.2 Retain immediate-publish as an explicit, privileged opt-in.** `submit(publication_mode="canonical-publication")` (or a friendlier `submit(immediate=True)`) stays available for the curator/admin doing trusted bulk loads. Default path for everyone else is staged.
- **1.3 Rewrite the `submit()` docstring.** The current text promises "records are published immediately… there is no separate approval step for your own submissions" — that becomes false and must say: submitted → pending review → promoted on passing the gate.
- **1.4 Make the return + stdout report the staged outcome** ("N records submitted → pending review; track with `ws.pending()`").

**Tests:** `test_submit_defaults_to_staged` (payload carries staged mode; no record goes live without promotion); `test_submit_immediate_requires_explicit_optin`.

---

## Phase 2 — `submit()` fails closed & observable (review P0)

**Goal:** submitting to staging must never silently lose records. Recontextualized from the review's top threat: no longer live-data-loss, but still a correctness-of-record-keeping requirement.

- **2.1** `_do_submit` ([ws.py:6147](BattINFO/src/battinfo/ws.py#L6147)) returns a **structured failure entry** (`{status:'failed', error, title}`) instead of `return []`; classify transient (retryable) vs client (terminal). *(R-1)*
- **2.2** `submit()` collects `(id, status, error)` per record, prints `Attempted N / succeeded M / failed K`, and **raises** (or returns `{submitted, failed}`) on any failure unless `allow_partial=True`; the `battinfo submit` CLI **exits non-zero** on failure. *(R-1)*
- **2.3 Up-front parse-all-before-submit pass:** validate + `json.loads` every session record file *before any network call*, fail closed on the first bad one with file context; wrap every per-record load (the five loops at ws.py:2781/2805/2851/2878/2905). Decide the **encoding policy** (read `utf-8-sig` to tolerate BOM, or fail-loud-with-filename on non-UTF-8) and apply it uniformly. *(R-2, R-10)*
- **2.4 Fix the registry exception contract in `api.py`** ([api.py:1461-1479](BattINFO/src/battinfo/api.py#L1461)): broaden `except` to `(HTTPError, URLError, TimeoutError, OSError)`; guard the success-path `json.loads` (raise `RuntimeError` on non-JSON 2xx); map a body-level `failed`/`rejected` to a non-ok status; add bounded **retry-with-backoff** on connection/timeout/429/500/502/503/504, never on other 4xx; raise typed `RegistryTransientError` vs `RegistryClientError`. *(R-3, R-4, C-7, A-1)*
- **2.5** Validate the `only=` filter — raise `ValueError` listing valid tokens on an unknown value ([ws.py:2691](BattINFO/src/battinfo/ws.py#L2691)) *(A-2)*; guard `submit()` against an empty-`_session_paths` "submit everything on disk" default — require an explicit `submit_all=True` *(R-9)*.

**Tests (the P0 fault-injection harness):** `tests/test_ws_submit.py` — one parametrized harness monkeypatching `submit_publication_package` to: raise 503, raise `TimeoutError`, return 200-non-JSON, return 200 body `status='failed'`, succeed-then-fail. Asserts: `submit()` raises or returns a structured succeeded/failed result (never a bare shorter list); CLI exits non-zero; "all failed" ≠ "no records". Plus `test_submit_fails_closed_on_corrupt_record` (raise before any network call), `test_submit_handles_bom_record_loudly`, and the four `test_api_submit.py` contract tests.

---

## Phase 3 — Canonical-record correctness (the archived artifact must be right)

**Goal:** because the canonical record is now the source of truth, these are the highest-value fixes. Nothing wrong may be mintable.

- **3.1 IRI disambiguation on BOTH minting paths** *(C-1, C-2, A-4)*:
  - Call `_disambiguate_entity_ids` for `finalized_cell_specs` and `finalized_test_specs` in `_finalize()` ([_workspace.py:1744-1763](BattINFO/src/battinfo/_workspace.py#L1744)) **before** cells/tests finalize, so re-minted spec ids propagate.
  - Fold a **content hash** (canonical record minus id) into the spec/entity seed so distinct content can never collide, and make collision re-mint **content-seeded** (not iteration-ordinal) so the same logical entity gets a stable IRI across runs/orderings.
  - Apply the same to the second minting path in `contribution.py` `_entity_iri` (~623-640), which currently never disambiguates.
  - Expose `mode` through `AuthoringWorkspace.save()` so the create-only overwrite guard is reachable.
- **3.2 Non-finite guard** *(C-3)*: add `return result if math.isfinite(result) else None` to `protocols._num` ([interop/protocols.py:54](BattINFO/src/battinfo/interop/protocols.py#L54)) (closes discovery/converter/protocols at once); extend the semantic non-finite check ([validate/semantic.py:423](BattINFO/src/battinfo/validate/semantic.py#L423)) to recurse into nested `property` quantity dicts so component/material specs fail closed regardless of importer.
- **3.3 Atomic durable writes** *(R-5)*: rewrite `_jsonio.write_json` ([_jsonio.py:29](BattINFO/src/battinfo/_jsonio.py#L29)) to temp-file + `flush` + `os.fsync` + `os.replace`; apply to the in-place writes at ws.py:3124/3296; fix `workspace_state._write_workspace` to **stage-then-swap** instead of `rmtree`-before-write (group blast-radius).
- **3.4 Importers fail closed / lossy-but-loud** *(D-5, D-6, IO-*)*: BDC drops non-numeric capacity → warn + populate `BdcImportPackage.warnings`; discovery dedupes phantom solvents; converter gains an optional `validate=`; every importer's output must pass `json.dumps(record, allow_nan=False)`.

**Tests:** `test_finalize_disambiguates_colliding_cell_specs`/`_test_specs` (distinct ids **and** two on-disk files); `test_disambiguation_is_order_independent`; `test_package_batch_disambiguates_colliding_specs` (second path); `test_num_rejects_non_finite` + `test_discovery_eln_nan_loading_dropped` + `test_create_component_spec_rejects_nan_quantity`; `test_write_json_is_atomic_on_failure` (interrupt **during** the OS write); `test_write_workspace_atomic_on_interrupt`.

---

## Phase 4 — The promotion gate (where "curated index" is enforced)

**Goal:** records reach the public genome only by passing automatable hard gates; a curator reviews only the residue. Curator-as-promoter, not curator-as-sole-ingestor. Builds on the existing `validate_staging_*` / `promote_staging_*` ([api.py:1051](BattINFO/src/battinfo/api.py#L1051)) and `pending()`/`approve()` primitives.

- **4.1 Define the promotion state machine + hard gates.** A staged submission auto-promotes iff **all** pass: (a) schema + semantic valid (`validate_record_report`), (b) ORCID-attributed contributor, (c) content-deduped against the index, (d) **a resolvable archive DOI is present**. Anything failing (a)–(c) is rejected with reasons; anything missing (d) stays in staging as "submitted, un-anchored." Everything else routes to curator review (`pending()`/`approve()`).
  - *Decision to confirm:* fully-automatic on gate-pass, or always-curator-for-first-N-per-publisher (trust ramp)? Recommend: auto-promote on full pass once dedup + DOI gates are solid; manual until then.
- **4.2 Kill the validation lie; unify the submission builders** *(C-6)*: `submit()` must run `validate_record_report(policy='publisher')` per record and carry the **real** report — never the hardcoded `validation:{ok:True}` ([ws.py:5918+](BattINFO/src/battinfo/ws.py#L5918)). Converge `ws.submit()` with `workspace_state.build_submission_package` (which already runs `check()` and raises) so there is **one** validation guarantee, not two opposite ones.
- **4.3 Dedup / idempotency** *(A-3)*: derive a **content hash** identity; treat a 409 signalling identical content as a **no-op success**, not a version-bump-and-re-POST; exclude free-running timestamps (`retrieved_at`/`created_at`/`generated_at`) from the IRI-and-version identity so reproducible re-authoring is byte-stable and stops minting `-v2/-v3` duplicates.
- **4.4 Wire the DOI as the promotion key:** ensure `submit(doi=...)` ([ws.py:2605](BattINFO/src/battinfo/ws.py#L2605)) threads the DOI into the submission payload provenance/citation so the gate can read it. "No DOI → stays in staging."

**Tests:** `test_promotion_gate_requires_valid_doi_orcid_dedup` (accept/reject per rule); `test_409_identical_content_does_not_duplicate`; `test_reauthored_record_bytes_stable`; `test_submit_validates_and_reports_real_validation` (no payload ever carries `validation.ok=True` for an invalid record).

> Registry-side promotion endpoint internals are out of BattINFO scope, but the **gate rules + status tokens are a shared contract** — coordinate them with the registry as part of this phase.

---

## Phase 5 — Archive-anchored ingestion + rebuildable index (the payoff)

**Goal:** realize the curated-index model — the archive carries the authoritative record; the registry is reconstructible from it.

- **5.1 Embed the canonical record in the Zenodo deposit.** Extend `ws.zenodo()` ([ws.py:3304](BattINFO/src/battinfo/ws.py#L3304)) to write the full canonical BattINFO JSON-LD (via `record_to_jsonld`, **with EMMO IRIs** — the currently-unused capability) as a first-class file in the deposit, so the source-of-truth record is archived alongside the data and minted with the DOI. **No lossy re-scrape:** the rich record travels with the archive.
- **5.2 Ingest/refresh the registry from the DOI.** The promotion step pulls the canonical record from the archived deposit (by DOI), not a re-derived scrape — guaranteeing the index mirrors the source of truth.
- **5.3 Gate the Zenodo publish** *(R-7)*: run `validate_publication_report` inside `zenodo()` **before** `publish_deposit` and raise on errors when `publish=True`; make `_bundle_data_files` warn on skipped `file://` distributions (parity with `ws.upload()`). Keep `publish=False` (draft) the default.
- **5.4 Guard plot/BDF reuse** *(C-4, C-5, R-8)*: stop trusting stale `.plot.json`/`.png`/`.bdf.parquet` via skip-if-exists — validate before reuse (parse JSON / check PNG magic bytes / integrity-check parquet), write via temp+`os.replace`, refuse to publish a degenerate/blank preview.
- **5.5 Establish the rebuild contract:** document and test that the public index is reconstructible from {archived canonical records + enrichment (Crossref/ROR/OpenAIRE)}. This is what lets you treat Neon as cache and is why the durability findings are now *moderate* rather than existential.
- **5.6 RDF fidelity** *(D-2, D-3)*: emit `schema:unitText` (literal) for unmapped units instead of leaking `file://` IRIs in `jsonld._quantity`; add an RDF round-trip assertion harness.

**Tests:** `test_zenodo_deposit_embeds_canonical_record`; `test_ingest_from_doi_roundtrips`; `test_zenodo_fails_closed_on_missing_distribution_file`; `test_process_does_not_publish_stale_plot`; `test_id_typed_objects_are_absolute_http_iris`; a `test_registry_rebuild_equivalence` smoke (rebuild from archived records → equivalent index).

---

## Phase 6 — Test architecture & CI gates

- **Coverage:** ratchet `fail_under` 72 → **74** immediately (current level, free); after the P0/P1 tests land, add **module-level floors** on `ws.py` submit path, `processing.py`, and the new promotion-gate code via a small CI assertion (a single global gate lets small high-coverage modules mask regression on the risky code). Keep `--disable-socket` / `--strict-markers` / `--timeout=300`; assert no test re-enables sockets.
- **Property-based / fuzz:** add `hypothesis` (dev dep); target `_num`/numeric coercion (never non-finite), IRI minting determinism + collision-disambiguation order-independence, JSON-LD round-trip (no `file://`), `_bump_version` over odd inputs.
- **Round-trip harness:** shared parametrization asserting `json.dumps(record, allow_nan=False)` over every importer fixture in `tests/fixtures/interop/`, and the record → jsonld → rdflib round-trip.
- **New suite:** `tests/test_promotion_gate.py` covering the Phase-4 gate rules.

---

## Sequencing (critical path) & parallelism

**Do-first (cheap, unblock everything):**
1. **3.3 atomic writes** — one localized change; removes the corruption precondition behind R-2/R-6/R-10.
2. **2.4 registry exception contract** — cheap; closes R-3/R-4/C-7/A-1.

**Then the front-door change (the user's headline ask):**
3. **Phase 1 (staged-by-default)** + **Phase 2 (fail-closed submit)** together — they touch the same `submit()`/`_do_submit` surface; do them as one change set with the P0 harness.

**Then correctness, gated by nothing above:**
4. **Phase 3.1/3.2 (IRI + NaN)** can proceed in parallel with Phases 1–2 (different code surfaces: `_workspace.py`/`interop` vs `ws.py` submit).

**Then the curated-index machinery:**
5. **Phase 4 (promotion gate)** depends on 3.1 (dedup needs content-hash identity) and 2.x (real validation). Coordinate the registry contract here.
6. **Phase 5 (archive-anchoring + rebuild)** depends on Phase 4 (DOI gate) and is the largest net-new piece.

**Phase 6 tests land alongside each phase, not at the end.**

```
3.3 ─┐
2.4 ─┼─► Phase 1+2 (submit: staged + fail-closed) ─┐
3.1 ─┴─► 3.2 ───────────────────────────────────────┼─► Phase 4 (promotion gate) ─► Phase 5 (archive + rebuild)
                                                     (registry contract coordination)
```

---

## Decisions to confirm (don't block starting Phases 1–3)

1. **Staged-mode token** the registry expects (`"staged-publication"`?) — Phase 1.
2. **Auto-promote policy:** fully automatic on gate-pass, or a per-publisher trust ramp (manual for first N)? — Phase 4.
3. **Keep immediate-publish** as a privileged curator opt-in (recommended) or remove it entirely? — Phase 1.
4. **DOI gate hardness:** is a resolvable DOI a *hard* requirement for promotion, or may some records live in a "submitted, un-anchored" public tier? — Phase 4.
5. **Canonical persistence of the index:** is the `curated_root` file store (battinfo-records) the rebuild source of truth, the registry DB, or both-with-the-archive-authoritative? — Phase 5.

---

## Appendix — review-finding → plan-phase map

| Finding | Phase |
|---|---|
| R-1 submit silent failure / CLI exit 0 | 2.1, 2.2 |
| R-2 unguarded `json.loads` aborts batch | 2.3 |
| R-3 non-JSON 2xx / R-4 read-timeout escape | 2.4 |
| R-5 non-atomic write / rmtree-first | 3.3 |
| R-6 silent sibling-link drop | 2.3, 5.5 |
| R-7 Zenodo publish not validation-gated | 5.3 |
| R-8 corrupt cached parquet | 5.4 |
| R-9 submit-without-save leftovers | 2.5 |
| R-10 BOM/latin-1 input | 2.3 |
| C-1/C-2 IRI collision + order-dependence (both paths) | 3.1 |
| C-3 NaN/Inf into quantities | 3.2 |
| C-4/C-5 stale/degenerate plots | 5.4 |
| C-6 hardcoded `validation:{ok:True}` / no EMMO IRIs | 4.2, 5.1 |
| C-7 body-status ignored on 2xx | 2.4 |
| A-1 no retry/classification | 2.4 |
| A-2 `only=` not validated | 2.5 |
| A-3 409 version-bump duplicates | 4.3 |
| A-4 save hardcodes upsert | 3.1 |
| A-5 Zenodo publish no retry | 2.4 (apply same pattern) |
| A-6 credentials perms / error-body scrub | 2.4 / hardening |
| A-7 config precedence | 4.4 (resolve + log registry target) |
| D-1 spec unit-coverage gaps | 3.2 |
| D-2/D-3 RDF `file://` leak / no round-trip test | 5.6 |
| D-4 preview-only validation | 5.3 |
| D-5 BDC capacity drop | 3.4 |
| D-6 converter/discovery importer gaps | 3.4 |
| D-7 file-grouping collapse | 3.4 |
| D-8 schema-version back-compat | 4.1 (gate) |
